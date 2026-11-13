"""Real isolated PostgreSQL tests; external provider requests always mocked."""

import json
import os
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from uuid import UUID

import httpx
import integration_db
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from test_jobs_integration import fixture_stack, start_live_fetch, wait_for_fetch
from test_jobs_integration import job_store as job_store

from app.config import Settings
from app.job_identity import identity_key
from app.job_tasks import execute_fetch
from app.models import Job
from app.sources.common import SourceError
from app.sources.greenhouse import fetch_greenhouse

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1", reason="Requires running Compose services"
)


def add_job(
    engine,
    source,
    external_id,
    *,
    title="Head of QA",
    company="Example Software — synthetic",
    location="Example City / Remote",
    age=0,
):
    now = datetime.now(UTC)
    with Session(engine) as session, session.begin():
        session.add(
            Job(
                source=source,
                external_id=external_id,
                title=title,
                company=company,
                location=location,
                description="Synthetic integration test",
                url="https://example.invalid/job",
                posted_at=now,
                fetched_at=now - timedelta(days=age),
                dedupe_key=identity_key(source, external_id, company, title, location),
            )
        )


def test_greenhouse_config_gate_and_query_snapshot(job_store, monkeypatch):
    _, client, publish = job_store
    assert client.post("/api/job-fetches", json={"source": "greenhouse"}).status_code == 409
    settings = Settings(
        live_job_fetch_enabled=True, greenhouse_board_token="", greenhouse_company_name=""
    )
    monkeypatch.setattr("app.jobs.get_settings", lambda: settings)
    assert not client.get("/api/job-source?source=greenhouse").json()["ready"]
    publish.assert_not_called()
    settings.greenhouse_board_token, settings.greenhouse_company_name = (
        "example",
        "Example Software — synthetic",
    )
    status = client.get("/api/job-source?source=greenhouse").json()
    assert status["ready"]
    response = client.post("/api/job-fetches", json={"source": "greenhouse"})
    assert response.status_code == 202
    assert response.json()["query"] == {
        "board": "example",
        "company": settings.greenhouse_company_name,
    }
    assert client.post("/api/job-fetches", json={"source": "all"}).status_code == 422


def test_real_greenhouse_adapter_persists_and_revives_expired_jobs(job_store, monkeypatch):
    engine, client, _ = job_store
    add_job(engine, "greenhouse", "example:1001", age=31)
    settings = Settings(
        live_job_fetch_enabled=True,
        greenhouse_board_token="example",
        greenhouse_company_name="Example Software — synthetic",
    )
    monkeypatch.setattr("app.jobs.get_settings", lambda: settings)
    monkeypatch.setattr("app.job_tasks.get_settings", lambda: settings)
    assert client.get("/api/jobs?source=greenhouse").json()["total"] == 0
    payload = json.loads(files("app.sources").joinpath("greenhouse.fixture.json").read_text())
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as provider:
        monkeypatch.setattr(
            "app.job_tasks.fetch_greenhouse",
            lambda query, config: fetch_greenhouse(query, config, client=provider),
        )
        response = client.post("/api/job-fetches", json={"source": "greenhouse"})
        execute_fetch(UUID(response.json()["id"]), "worker@test")
    jobs = client.get("/api/jobs?source=greenhouse").json()
    assert jobs["total"] == 2
    assert all(job["date_kind"] == "updated" and not job["expired"] for job in jobs["items"])
    assert client.get(f"/api/job-fetches/{response.json()['id']}").json()["status"] == "succeeded"
    assert client.post("/api/job-fetches", json={"source": "greenhouse"}).status_code == 429


def test_combined_feed_groups_before_paging_and_preserves_origins(job_store):
    engine, client, _ = job_store
    add_job(engine, "adzuna", "1")
    add_job(engine, "greenhouse", "board:1")
    add_job(engine, "greenhouse", "board:2", title="Different opening")
    add_job(engine, "adzuna", "extra-1", title="Different adzuna opening")
    pages = [
        client.get(f"/api/jobs?source=all&limit=1&offset={offset}").json() for offset in range(3)
    ]
    assert all((page["total"], page["raw_total"]) == (3, 4) for page in pages)
    assert all(len(page["items"]) == 1 for page in pages)
    items = [item for page in pages for item in page["items"]]
    assert len({item["external_id"] for item in items}) == 3
    merged = next(job for job in items if job["title"] == "Head of QA")
    assert {origin["source"] for origin in merged["origins"]} == {"adzuna", "greenhouse"}
    assert client.get("/api/jobs?source=greenhouse").json()["total"] == 2
    with Session(engine) as session:
        assert len(session.scalars(select(Job)).all()) == 4


def test_expiration_keeps_records_and_fresh_duplicate_visible(job_store, monkeypatch):
    engine, client, _ = job_store
    add_job(engine, "adzuna", "old", age=31)
    add_job(engine, "greenhouse", "fresh", age=1)
    add_job(engine, "greenhouse", "old-only", title="Old opening", age=31)
    active = client.get("/api/jobs?source=all").json()
    assert (active["total"], active["raw_total"]) == (1, 1)
    assert not active["items"][0]["expired"]
    archive = client.get("/api/jobs?source=all&include_expired=true").json()
    assert (archive["total"], archive["raw_total"]) == (2, 3)
    merged = next(job for job in archive["items"] if job["title"] == "Head of QA")
    assert not merged["expired"] and sum(origin["expired"] for origin in merged["origins"]) == 1
    monkeypatch.setattr("app.jobs.get_settings", lambda: Settings(job_retention_days=60))
    assert client.get("/api/jobs?source=all").json()["raw_total"] == 3


def test_migration_backfills_existing_rows_without_losing_data(job_store):
    engine, _, _ = job_store
    # Guarded downgrade and upgrade (plan + single-use token); the legacy row is written by
    # the owner because the runtime guard rightly refuses a schema behind the code head.
    integration_db.migrate_engine_schema(engine, operation="downgrade", target="0003")
    owner = integration_db.owner_engine_for(engine)
    try:
        with owner.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO jobs(source,external_id,title,company,location,description,url,"
                    "posted_at,fetched_at) VALUES ('adzuna','legacy','Head of QA',"
                    "'Example Software','Springfield','original description',"
                    "'https://example.invalid/job',now(),now())"
                )
            )
    finally:
        owner.dispose()
    integration_db.migrate_engine_schema(engine)
    with Session(engine) as session:
        job = session.get(Job, ("adzuna", "legacy"))
        assert job.description == "original description"
        assert job.date_kind == "posted"
        assert job.dedupe_key == identity_key(
            job.source, job.external_id, job.company, job.title, job.location
        )


def test_one_source_failure_preserves_other_source_results(job_store, monkeypatch):
    engine, client, _ = job_store
    add_job(engine, "adzuna", "survives")
    before = client.get("/api/jobs?source=all").json()
    settings = Settings(
        live_job_fetch_enabled=True,
        greenhouse_board_token="example",
        greenhouse_company_name="Example Company",
    )
    monkeypatch.setattr("app.jobs.get_settings", lambda: settings)

    def fail(query, config):
        raise SourceError("provider_unavailable", "Greenhouse is temporarily unavailable.")

    monkeypatch.setattr("app.job_tasks.fetch_greenhouse", fail)
    response = client.post("/api/job-fetches", json={"source": "greenhouse"})
    execute_fetch(UUID(response.json()["id"]), "worker@test")
    assert client.get(f"/api/job-fetches/{response.json()['id']}").json()["status"] == "failed"
    assert client.get("/api/jobs?source=all").json() == before


@fixture_stack
def test_real_two_source_aggregation_through_broker():
    with httpx.Client(base_url="http://api:8000", timeout=20) as client:
        for source in ("adzuna", "greenhouse"):
            run = wait_for_fetch(client, start_live_fetch(client, source))
            assert run["worker"].startswith("worker@")
        combined = client.get("/api/jobs?source=all").json()
        assert combined["total"] == 3 and combined["raw_total"] == 4
        merged = next(job for job in combined["items"] if job["title"] == "Head of QA")
        assert {origin["source"] for origin in merged["origins"]} == {"adzuna", "greenhouse"}
