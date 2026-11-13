"""Isolated job storage/error tests plus a real broker/worker round trip."""

import json
import os
import time
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import httpx
import integration_db
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_session
from app.job_tasks import execute_fetch
from app.main import app
from app.models import Job, JobFetch, Profile
from app.sources.adzuna import SourceError, fetch_adzuna

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1", reason="Requires running Compose services"
)
# Tests that fetch through the running stack only run where the worker serves fixture
# data; they must never reach a live provider from a development stack.
fixture_stack = pytest.mark.skipif(
    os.environ.get("NEXTUP_FIXTURE_DATA_MODE", "").lower() != "true",
    reason="Requires the fixture-fetch CI stack",
)
# Provider settings the running container may carry (for example the CI stack's fixture
# mode and synthetic credentials) must not leak into Settings built inside tests.
PROVIDER_ENV = (
    "NEXTUP_LIVE_JOB_FETCH_ENABLED",
    "NEXTUP_FIXTURE_DATA_MODE",
    "NEXTUP_ADZUNA_APP_ID_FILE",
    "NEXTUP_ADZUNA_APP_KEY_FILE",
    "NEXTUP_GREENHOUSE_BOARD_TOKEN",
    "NEXTUP_GREENHOUSE_COMPANY_NAME",
    "NEXTUP_JOB_FETCH_MIN_INTERVAL_SECONDS",
)


def expire_rate_limit(engine, source="adzuna"):
    """Age the latest fetch record so that the rate-limit window has passed."""
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(JobFetch)
            .where(JobFetch.source == source)
            .order_by(JobFetch.created_at.desc())
            .limit(1)
        )
        if row:
            row.created_at = datetime.now(UTC) - timedelta(seconds=120)


def remove_profile(engine):
    """Drop the synthetic profile the fixture seeds, for tests of no-profile behavior."""
    with Session(engine) as session, session.begin():
        profile = session.get(Profile, 1)
        if profile:
            session.delete(profile)


def start_live_fetch(client, source):
    """Queue a fetch in the running stack, waiting out an earlier test's rate-limit window."""
    deadline = time.monotonic() + 90
    while True:
        response = client.post("/api/job-fetches", json={"source": source})
        if response.status_code != 429 or time.monotonic() > deadline:
            assert response.status_code == 202, response.text
            return response.json()["id"]
        time.sleep(min(int(response.headers.get("Retry-After", "1")), 15))


def wait_for_fetch(client, run_id):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        run = client.get(f"/api/job-fetches/{run_id}").json()
        if run["status"] == "succeeded":
            return run
        assert run["status"] in ("queued", "running"), run
        time.sleep(0.25)
    pytest.fail("Fetch did not complete in the real worker")


@pytest.fixture
def job_store(monkeypatch):
    # Owner-created schema, INIT through the guard (plan + apply), app-role engine.
    schema = integration_db.create_schema("nextup_jobs_test")
    integration_db.migrate_schema(schema)
    engine = integration_db.runtime_engine(schema)

    def sessions():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    monkeypatch.setattr("app.job_tasks.get_engine", lambda: engine)
    monkeypatch.setattr("app.db.get_engine", lambda: engine)  # FastAPI lifespan guard
    publish = MagicMock()
    monkeypatch.setattr("app.jobs.fetch_jobs.apply_async", publish)
    for key in PROVIDER_ENV:
        monkeypatch.delenv(key, raising=False)
    settings = Settings(
        live_job_fetch_enabled=True,
        adzuna_app_id="test",
        adzuna_app_key="secret",
        job_fetch_min_interval_seconds=10,
    )
    monkeypatch.setattr("app.jobs.get_settings", lambda: settings)
    # The worker path must use the mocked adapters below, never the CI fixture mode.
    monkeypatch.setattr("app.job_tasks.get_settings", lambda: settings)
    with Session(engine) as session, session.begin():
        session.add(
            Profile(
                id=1,
                skills=["Python"],
                target_titles=["Head of QA"],
                location="Example City",
                work_preferences=["remote"],
            )
        )
    _adzuna_payload = json.loads(files("app.sources").joinpath("adzuna.fixture.json").read_text())

    def _test_fetch_adzuna(query, config):
        import app.job_tasks

        return app.job_tasks.normalize_response(_adzuna_payload)

    monkeypatch.setattr("app.job_tasks.fetch_adzuna", _test_fetch_adzuna)
    try:
        with TestClient(app) as client:
            yield engine, client, publish
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
        integration_db.drop_schema(schema)


def test_adzuna_execution_is_idempotent_and_source_separated(job_store):
    engine, client, publish = job_store
    response = client.post("/api/job-fetches", json={"source": "adzuna"})
    assert response.status_code == 202
    run_id = response.json()["id"]
    publish.assert_called_once_with(task_id=run_id, retry=False)
    execute_fetch(UUID(run_id), "worker@test")
    original = client.get(f"/api/job-fetches/{run_id}").json()
    assert original["status"] == "succeeded" and original["stored_count"] == 2
    execute_fetch(UUID(run_id), "worker@duplicate")
    assert client.get(f"/api/job-fetches/{run_id}").json() == original
    assert client.get("/api/jobs?source=adzuna&limit=1").json()["total"] == 2
    assert len(client.get("/api/jobs?source=adzuna&limit=1").json()["items"]) == 1
    assert client.get("/api/jobs?source=greenhouse").json()["total"] == 0
    with Session(engine) as session:
        assert session.scalar(select(Job).limit(1)).source == "adzuna"


def test_live_fetch_requires_opt_in_credentials_and_profile(job_store, monkeypatch):
    engine, client, publish = job_store
    remove_profile(engine)
    for settings in (
        Settings(live_job_fetch_enabled=False),
        Settings(live_job_fetch_enabled=True, adzuna_app_id="", adzuna_app_key=""),
        Settings(live_job_fetch_enabled=True, adzuna_app_id="test", adzuna_app_key="secret"),
    ):
        monkeypatch.setattr("app.jobs.get_settings", lambda s=settings: s)
        assert client.post("/api/job-fetches", json={"source": "adzuna"}).status_code == 409
    publish.assert_not_called()
    assert "secret" not in client.get("/api/job-source").text


def test_profile_snapshot_is_used_for_live_fetch_and_failure_is_persisted(job_store, monkeypatch):
    engine, client, _ = job_store
    settings = Settings(live_job_fetch_enabled=True, adzuna_app_id="test", adzuna_app_key="secret")
    monkeypatch.setattr("app.jobs.get_settings", lambda: settings)
    with Session(engine) as session, session.begin():
        session.merge(
            Profile(
                id=1,
                skills=["Python"],
                target_titles=["Head of QA", "Director"],
                location="Example City",
                work_preferences=["remote"],
            )
        )
    response = client.post("/api/job-fetches", json={"source": "adzuna"})
    assert response.status_code == 202
    expected = {"what": "Head of QA", "where": "Example City"}
    assert response.json()["query"] == expected
    adapter = MagicMock(
        side_effect=SourceError("authentication", "Adzuna rejected the configured credentials.")
    )
    monkeypatch.setattr("app.job_tasks.fetch_adzuna", adapter)
    execute_fetch(UUID(response.json()["id"]), "worker@test")
    adapter.assert_called_once()
    assert adapter.call_args.args[0] == expected
    failed = client.get(f"/api/job-fetches/{response.json()['id']}").json()
    assert failed["status"] == "failed" and failed["error_code"] == "authentication"
    assert client.get("/api/jobs?source=adzuna").json()["total"] == 0
    assert client.post("/api/job-fetches", json={"source": "adzuna"}).status_code == 429


def test_pending_fetch_is_rejected(job_store):
    _, client, publish = job_store
    first = client.post("/api/job-fetches", json={"source": "adzuna"})
    assert first.status_code == 202
    assert client.post("/api/job-fetches", json={"source": "adzuna"}).status_code == 409
    assert publish.call_count == 1


def test_refresh_updates_existing_jobs_and_failure_preserves_them(job_store, monkeypatch):
    engine, client, _ = job_store
    for _ in range(2):
        expire_rate_limit(engine)
        response = client.post("/api/job-fetches", json={"source": "adzuna"})
        assert response.status_code == 202
        execute_fetch(UUID(response.json()["id"]), "worker@test")
        assert client.get("/api/jobs?source=adzuna").json()["total"] == 2
    before = client.get("/api/jobs?source=adzuna").json()
    monkeypatch.setattr(
        "app.job_tasks.normalize_response",
        MagicMock(side_effect=SourceError("invalid_response", "Invalid results document.")),
    )
    expire_rate_limit(engine)
    response = client.post("/api/job-fetches", json={"source": "adzuna"})
    execute_fetch(UUID(response.json()["id"]), "worker@test")
    assert client.get(f"/api/job-fetches/{response.json()['id']}").json()["status"] == "failed"
    assert client.get("/api/jobs?source=adzuna").json() == before


def test_empty_fetch_is_successful_without_erasing_saved_jobs(job_store, monkeypatch):
    engine, client, _ = job_store
    response = client.post("/api/job-fetches", json={"source": "adzuna"})
    execute_fetch(UUID(response.json()["id"]), "worker@test")
    monkeypatch.setattr("app.job_tasks.normalize_response", lambda payload: ([], 0, 0))
    expire_rate_limit(engine)
    response = client.post("/api/job-fetches", json={"source": "adzuna"})
    execute_fetch(UUID(response.json()["id"]), "worker@test")
    run = client.get(f"/api/job-fetches/{response.json()['id']}").json()
    assert run["status"] == "succeeded" and run["stored_count"] == 0
    assert client.get("/api/jobs?source=adzuna").json()["total"] == 2


def test_adzuna_adapter_results_are_normalized_and_persisted(job_store, monkeypatch):
    engine, client, _ = job_store
    settings = Settings(live_job_fetch_enabled=True, adzuna_app_id="test", adzuna_app_key="secret")
    monkeypatch.setattr("app.jobs.get_settings", lambda: settings)
    monkeypatch.setattr("app.job_tasks.get_settings", lambda: settings)
    response = client.post("/api/job-fetches", json={"source": "adzuna"})
    assert response.status_code == 202
    payload = json.loads(files("app.sources").joinpath("adzuna.fixture.json").read_text())
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as provider:
        monkeypatch.setattr(
            "app.job_tasks.fetch_adzuna",
            lambda query, config: fetch_adzuna(query, config, client=provider),
        )
        execute_fetch(UUID(response.json()["id"]), "worker@test")
    assert len(requests) == 1
    assert requests[0].url.params["what"] == "Head of QA"
    jobs = client.get("/api/jobs?source=adzuna").json()
    assert jobs["total"] == 2
    assert {job["source"] for job in jobs["items"]} == {"adzuna"}
    assert all("<strong>" not in job["title"] for job in jobs["items"])
    assert client.get("/api/jobs?source=greenhouse").json()["total"] == 0


def test_publish_failure_is_recorded(job_store):
    _, client, publish = job_store
    publish.side_effect = ConnectionError("private connection details")
    response = client.post("/api/job-fetches", json={"source": "adzuna"})
    assert response.status_code == 503
    assert "private" not in response.text
    last = client.get("/api/job-fetches/latest?source=adzuna").json()
    assert last["status"] == "publish_failed"
    assert last["recovery_deadline"] is not None and last["completed_at"] is None
    assert client.post("/api/job-fetches", json={"source": "adzuna"}).status_code == 409
    assert publish.call_count == 1


def test_invalid_source_paging_and_missing_run(job_store):
    _, client, _ = job_store
    assert client.post("/api/job-fetches", json={"source": "unknown"}).status_code == 422
    assert client.get("/api/jobs?limit=10000").status_code == 422
    assert client.get("/api/jobs?offset=-1").status_code == 422
    assert client.get(f"/api/job-fetches/{uuid4()}").status_code == 404


@fixture_stack
def test_real_broker_worker_persistence():
    # Only the two explicitly synthetic fixture records are updated in the running
    # CI stack. No user profile or live-provider records are modified.
    with httpx.Client(base_url="http://api:8000", timeout=20) as client:
        run_id = start_live_fetch(client, "adzuna")
        run = wait_for_fetch(client, run_id)
        assert run["worker"].startswith("worker@")
        assert run["stored_count"] == 2
        assert client.get("/api/jobs?source=adzuna").json()["total"] >= 2
    stack = integration_db.stack_engine()  # runtime role on the stack's own database
    try:
        with Session(stack) as session:
            job = session.get(Job, ("adzuna", "test-qa-director"))
            assert job.title == "Director of Quality Engineering"
    finally:
        stack.dispose()
