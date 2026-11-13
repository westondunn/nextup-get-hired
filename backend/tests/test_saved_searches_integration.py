"""Saved searches and dashboard summaries in isolated PostgreSQL schemas."""

import os
from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_aggregation_integration import add_job
from test_jobs_integration import job_store as job_store
from test_jobs_integration import remove_profile
from test_scoring_integration import PROFILE
from test_scoring_integration import add_job as add_scored_job

from app.models import SavedSearch

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1", reason="Requires running Compose services"
)
SEARCH = {
    "name": "QA shortlist",
    "source": "all",
    "include_expired": True,
    "filters": {
        "q": "Python QA",
        "company": "Example",
        "location": "Springfield",
        "exclude": "intern, contract",
        "work_mode": "remote",
        "min_score": 70,
        "max_age_days": 30,
        "sort": "score",
        "discovery_only": False,
    },
}


def test_saved_search_create_reload_replace_delete_without_fetching(job_store):
    engine, client, publish = job_store
    assert client.put("/api/profile", json=PROFILE).status_code == 200
    add_job(engine, "adzuna", "preserved")
    assert client.get("/api/saved-searches").json() == []
    result = client.post("/api/saved-searches", json=SEARCH)
    assert result.status_code == 201
    saved = result.json()
    assert {key: saved[key] for key in SEARCH} == SEARCH
    with Session(engine) as session:
        row = session.get(SavedSearch, UUID(saved["id"]))
        assert row.filters == SEARCH["filters"]
        assert row.name_key == "qa shortlist"
    assert client.get("/api/saved-searches").json() == [saved]
    replacement = SEARCH | {"name": "Remote QA", "source": "all", "include_expired": False}
    updated = client.put(f"/api/saved-searches/{saved['id']}", json=replacement)
    assert updated.status_code == 200
    assert updated.json()["created_at"] == saved["created_at"]
    assert updated.json()["updated_at"] >= saved["updated_at"]
    assert {key: updated.json()[key] for key in replacement} == replacement
    assert client.delete(f"/api/saved-searches/{saved['id']}").status_code == 204
    assert client.get("/api/saved-searches").json() == []
    with Session(engine) as session:
        assert session.scalars(select(SavedSearch)).all() == []
    assert client.get("/api/profile").json() == PROFILE
    assert client.get("/api/jobs?source=adzuna").json()["total"] == 1
    publish.assert_not_called()


def test_duplicate_names_are_rejected_without_overwriting_searches(job_store):
    _, client, _ = job_store
    first = client.post("/api/saved-searches", json=SEARCH).json()
    assert (
        client.post("/api/saved-searches", json=SEARCH | {"name": "  qa   SHORTLIST  "}).status_code
        == 409
    )
    second = client.post("/api/saved-searches", json=SEARCH | {"name": "Another"}).json()
    assert client.put(f"/api/saved-searches/{second['id']}", json=SEARCH).status_code == 409
    rows = client.get("/api/saved-searches").json()
    assert [row["name"] for row in rows] == ["Another", "QA shortlist"]
    assert next(row for row in rows if row["id"] == first["id"]) == first


@pytest.mark.parametrize(
    "change",
    [
        {"name": "   "},
        {"name": "x" * 81},
        {"name": "bad\x00name"},
        {"source": "unsupported"},
        {"include_expired": "false"},
        {"schedule": "daily"},
        {"filters": {"q": "x" * 161}},
        {"filters": {"q": "bad\x00query"}},
        {"filters": {"min_score": 101}},
        {"filters": {"min_score": "70"}},
        {"filters": {"min_score": True}},
        {"filters": {"max_age_days": -1}},
        {"filters": {"work_mode": "anything"}},
        {"filters": {"sort": "random"}},
        {"filters": {"credentials": "never stored"}},
    ],
)
def test_invalid_saved_search_has_no_side_effects(job_store, change):
    _, client, publish = job_store
    assert client.post("/api/saved-searches", json=SEARCH | change).status_code == 422
    assert client.get("/api/saved-searches").json() == []
    publish.assert_not_called()


def test_missing_search_and_defaults(job_store):
    _, client, _ = job_store
    path = f"/api/saved-searches/{uuid4()}"
    assert client.delete(path).status_code == 404
    assert client.put(path, json=SEARCH).status_code == 404
    assert client.delete("/api/saved-searches/not-a-uuid").status_code == 422
    result = client.post("/api/saved-searches", json={"name": " Minimal ", "source": "adzuna"})
    assert result.status_code == 201
    assert result.json()["name"] == "Minimal"
    assert not result.json()["include_expired"]
    assert result.json()["filters"]["min_score"] is None


def test_summary_covers_all_filtered_groups_before_pagination(job_store):
    engine, client, _ = job_store
    remove_profile(engine)
    add_job(engine, "adzuna", "qa")
    add_job(engine, "greenhouse", "qa")
    add_job(engine, "greenhouse", "other", title="Another opening")
    add_job(engine, "adzuna", "old", title="Old opening", age=31)
    first = client.get("/api/jobs?source=all&limit=1").json()
    second = client.get("/api/jobs?source=all&limit=1&offset=1").json()
    expected = {
        "results": 2,
        "source_records": 3,
        "high_score_results": None,
        "average_score": None,
        "expired_results": 0,
        "source_counts": {"adzuna": 1, "greenhouse": 2, "lever": 0, "ashby": 0, "reference": 0},
    }
    assert len(first["items"]) == len(second["items"]) == 1
    assert first["summary"] == second["summary"] == expected
    filtered = client.get("/api/jobs?source=all&q=Head%20QA").json()["summary"]
    assert filtered["results"] == 1 and filtered["source_records"] == 2
    archive = client.get("/api/jobs?source=all&include_expired=true").json()["summary"]
    assert archive["results"] == 3 and archive["expired_results"] == 1
    empty = client.get("/api/jobs?source=all&q=absent").json()["summary"]
    assert empty["results"] == 0 and empty["average_score"] is None


def test_summary_scores_use_representatives_not_duplicate_source_scores(job_store, monkeypatch):
    engine, client, _ = job_store
    monkeypatch.setattr("app.jobs.scoring.utc_day", lambda: date(2026, 10, 30))
    assert client.put("/api/profile", json=PROFILE).status_code == 200
    add_scored_job(engine, "strong")
    add_scored_job(engine, "duplicate", source="greenhouse")
    add_scored_job(engine, "weak", title="Marketing Intern", description="Marketing")
    summary = client.get("/api/jobs?source=all&limit=1").json()["summary"]
    assert summary["results"] == 2 and summary["source_records"] == 3
    assert summary["high_score_results"] == 1
    assert summary["average_score"] == 69  # (100 + 38) / 2, duplicate not counted twice.
    empty = client.get("/api/jobs?source=all&q=absent").json()["summary"]
    assert empty["high_score_results"] == 0 and empty["average_score"] is None
