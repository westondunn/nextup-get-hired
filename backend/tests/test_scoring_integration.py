"""Scoring/filtering against isolated real PostgreSQL, never a user's profile."""

import os
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlalchemy.orm import Session
from test_jobs_integration import expire_rate_limit, remove_profile
from test_jobs_integration import job_store as job_store

from app.job_identity import identity_key
from app.job_tasks import execute_fetch
from app.models import Job

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1", reason="Requires running Compose services"
)
PROFILE = {
    "skills": ["Python", "C++"],
    "target_titles": ["Head of QA"],
    "location": "Springfield",
    "work_preferences": ["remote"],
}


def add_job(
    engine,
    external_id,
    *,
    source="adzuna",
    title="Head of QA",
    description="Python and C++",
    location="Springfield / Remote",
):
    with Session(engine) as session, session.begin():
        session.add(
            Job(
                source=source,
                external_id=external_id,
                title=title,
                description=description,
                company="Example",
                location=location,
                url="https://example.invalid/job",
                posted_at=datetime(2026, 10, 30, tzinfo=UTC),
                fetched_at=datetime.now(UTC),
                date_kind="posted",
                dedupe_key=identity_key(source, external_id, "Example", title, location),
            )
        )


def test_unscored_is_distinct_from_zero_and_score_queries_require_profile(job_store):
    engine, client, _ = job_store
    remove_profile(engine)
    add_job(engine, "no-profile")
    page = client.get("/api/jobs").json()
    assert not page["scoring_available"]
    assert page["items"][0]["score"] is None and page["items"][0]["score_breakdown"] is None
    assert client.get("/api/jobs?min_score=0").status_code == 409
    assert client.get("/api/jobs?sort=score").status_code == 409
    assert client.get("/api/jobs?q=Python").json()["total"] == 1


def test_score_cache_refreshes_after_profile_listing_and_day_changes(job_store, monkeypatch):
    engine, client, _ = job_store
    monkeypatch.setattr("app.jobs.scoring.utc_day", lambda: date(2026, 10, 30))
    add_job(engine, "cached")
    assert client.put("/api/profile", json=PROFILE).status_code == 200
    first = client.get("/api/jobs?sort=score").json()["items"][0]
    assert first["score"] == 100
    with Session(engine) as session:
        row = session.get(Job, ("adzuna", "cached"))
        original_signature = row.score_signature
        assert row.score == 100 and row.score_breakdown == first["score_breakdown"]
    assert client.get("/api/jobs").json()["items"][0]["score_breakdown"] == first["score_breakdown"]
    client.put("/api/profile", json=PROFILE | {"skills": ["Java"]})
    assert client.get("/api/jobs").json()["items"][0]["score"] == 65
    with Session(engine) as session, session.begin():
        row = session.get(Job, ("adzuna", "cached"))
        assert row.score_signature != original_signature
        row.description = "Java"
    assert client.get("/api/jobs").json()["items"][0]["score"] == 100
    monkeypatch.setattr("app.jobs.scoring.utc_day", lambda: date(2026, 11, 8))
    refreshed = client.get("/api/jobs").json()["items"][0]
    assert refreshed["score"] == 97
    assert refreshed["score_breakdown"]["as_of"] == "2026-11-08"


def test_filters_ranking_and_pagination_are_applied_in_correct_order(job_store, monkeypatch):
    engine, client, _ = job_store
    monkeypatch.setattr("app.jobs.scoring.utc_day", lambda: date(2026, 10, 30))
    client.put("/api/profile", json=PROFILE)
    add_job(engine, "weak", title="Marketing Intern", description="Marketing")
    add_job(engine, "strong")
    first = client.get("/api/jobs?sort=score&limit=1").json()
    assert first["total"] == 2 and first["items"][0]["external_id"] == "strong"
    assert (
        client.get("/api/jobs?sort=score&limit=1&offset=1").json()["items"][0]["external_id"]
        == "weak"
    )
    filtered = client.get(
        "/api/jobs?q=python&company=Example&location=Springfield&exclude=intern&work_mode=remote&min_score=90&max_age_days=7"
    ).json()
    assert filtered["total"] == 1 and filtered["items"][0]["external_id"] == "strong"
    assert client.get("/api/jobs?exclude=head%20of%20qa").json()["total"] == 1
    for path in ["min_score=101", "max_age_days=-1", "work_mode=invalid", "sort=invalid"]:
        assert client.get("/api/jobs?" + path).status_code == 422


def test_group_scores_come_from_one_matching_record_and_preserve_all_origins(
    job_store, monkeypatch
):
    engine, client, _ = job_store
    monkeypatch.setattr("app.jobs.scoring.utc_day", lambda: date(2026, 10, 30))
    client.put("/api/profile", json=PROFILE)
    add_job(engine, "a", description="Python")
    add_job(engine, "b", source="greenhouse", description="C++")
    page = client.get("/api/jobs?source=all&sort=score&q=python&limit=1").json()
    assert (page["total"], page["raw_total"]) == (1, 2)
    item = page["items"][0]
    assert item["external_id"] == "a" and item["score"] == 83
    assert len(item["origins"]) == 2
    assert sum(part["points"] for part in item["score_breakdown"]["components"]) == item["score"]
    assert client.get("/api/jobs?source=all&min_score=90").json()["total"] == 0


def test_ingestion_invalidates_cached_scores_without_changing_profile(job_store):
    engine, client, _ = job_store
    client.put("/api/profile", json=PROFILE)
    for _ in range(2):
        expire_rate_limit(engine)
        response = client.post("/api/job-fetches", json={"source": "adzuna"})
        execute_fetch(UUID(response.json()["id"]), "worker@test")
        with Session(engine) as session:
            row = session.get(Job, ("adzuna", "test-head-qa"))
            assert row.score is None and row.score_signature is None
        assert client.get("/api/jobs?source=adzuna").json()["items"][0]["score"] is not None
    assert client.get("/api/profile").json() == PROFILE
