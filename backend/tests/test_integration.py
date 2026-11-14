"""Opt-in tests against the running Compose stack, with real broker delivery."""

import os
import time
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.models import DiagnosticRun
from app.tasks import run_diagnostic

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1", reason="Requires running Compose services"
)


def wait_for_result(client, run_id):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        response = client.get(f"/api/diagnostics/{run_id}")
        response.raise_for_status()
        if response.json()["status"] == "succeeded":
            return response.json()
        time.sleep(0.25)
    pytest.fail(f"Worker did not finish diagnostic {run_id} within 30 seconds")


def test_broker_worker_postgres_round_trip():
    with httpx.Client(base_url="http://api:8000", timeout=20) as client:
        response = client.post("/api/diagnostics")
        assert response.status_code == 202
        run_id = response.json()["id"]
        result = wait_for_result(client, run_id)
    assert result["worker"].startswith("worker@")
    with Session(get_engine()) as session:
        persisted = session.get(DiagnosticRun, UUID(run_id))
        assert persisted.status == "succeeded"
        assert persisted.result["message"] == "Worker reached PostgreSQL"
        assert persisted.completed_at.isoformat() == result["completed_at"].replace("Z", "+00:00")


def test_duplicate_delivery_preserves_first_completion():
    with httpx.Client(base_url="http://api:8000", timeout=20) as client:
        response = client.post("/api/diagnostics")
        assert response.status_code == 202
        run_id = response.json()["id"]
        original = wait_for_result(client, run_id)
        run_diagnostic.apply_async(task_id=run_id, kwargs={"source": "manual"})
        # A sentinel behind the duplicate on the same single-worker FIFO queue proves consumption.
        sentinel = client.post("/api/diagnostics")
        assert sentinel.status_code == 202
        wait_for_result(client, sentinel.json()["id"])
        assert client.get(f"/api/diagnostics/{run_id}").json() == original


def test_scheduler_delivers_to_postgres():
    started_at = datetime.now(UTC)
    timeout = get_settings().diagnostic_interval_seconds + 30
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with Session(get_engine()) as session:
            run = session.scalar(
                select(DiagnosticRun)
                .where(
                    DiagnosticRun.source == "scheduler",
                    DiagnosticRun.status == "succeeded",
                    DiagnosticRun.completed_at >= started_at,
                )
                .order_by(DiagnosticRun.completed_at.desc())
            )
            if run:
                assert run.worker.startswith("worker@")
                assert run.result["message"] == "Worker reached PostgreSQL"
                return
        time.sleep(1)
    pytest.fail(f"No new persisted scheduler delivery within {timeout} seconds")


def test_local_session_round_trip_against_the_real_store():
    """Start, use and end a session through the running api and Redis.

    Assertions compare status codes and flags only, so a failure never prints the code.
    """
    code = get_settings().setup_code.get_secret_value()
    assert len(code) >= 24, "the api service must receive the setup code file"
    with httpx.Client(base_url="http://api:8000", timeout=20) as client:
        assert client.get("/api/session").json() == {"configured": True, "active": False}
        invalid = {"enabled": "not-a-boolean"}  # fails validation, so nothing is ever saved
        assert client.put("/api/correspondence", json=invalid).status_code == 401
        assert client.post("/api/correspondence/sync").status_code == 401
        refused = client.post("/api/session", json={"code": "not-the-setup-code"})
        assert refused.status_code == 401
        assert client.get("/api/session").json()["active"] is False
        started = client.post("/api/session", json={"code": code})
        assert started.status_code == 204
        assert client.get("/api/session").json() == {"configured": True, "active": True}
        assert client.put("/api/correspondence", json=invalid).status_code == 422
        assert client.delete("/api/session").status_code == 204
        assert client.get("/api/session").json()["active"] is False
        assert client.put("/api/correspondence", json=invalid).status_code == 401
