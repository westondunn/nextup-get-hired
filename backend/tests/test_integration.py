"""Opt-in tests against the running Compose stack, with real broker delivery."""

import os
import time
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import token_vault
from app.config import get_settings
from app.db import get_engine
from app.models import DiagnosticRun, GoogleConnection
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


def test_the_api_container_can_encrypt_with_the_mounted_token_key():
    """The key file reaches this service, and a value sealed with it opens again.

    Assertions compare lengths and flags only, so a failure never prints the key.
    """
    assert len(get_settings().token_key.get_secret_value()) >= token_vault.MIN_KEY_LENGTH
    assert token_vault.available()
    sealed = token_vault.seal("synthetic value", purpose="integration-test")
    assert sealed.startswith("v1.") and "synthetic value" not in sealed
    assert token_vault.open_sealed(sealed, purpose="integration-test") == "synthetic value"


def test_the_api_container_can_store_a_sealed_credential_in_the_connection_table():
    """The runtime role of the real stack can use the table, with the mounted key.

    The row is synthetic and is removed again, so the stack is left with no connection.
    """
    purpose = "integration-test"
    with Session(get_engine()) as session, session.begin():
        assert session.get(GoogleConnection, 1) is None
    try:
        with Session(get_engine()) as session, session.begin():
            session.add(
                GoogleConnection(
                    id=1,
                    client_id="synthetic-client",
                    client_secret_sealed=token_vault.seal("synthetic value", purpose=purpose),
                )
            )
        with Session(get_engine()) as session, session.begin():
            row = session.scalar(select(GoogleConnection).with_for_update())
            assert (row.state, row.key_version) == ("not_connected", 1)
            assert "synthetic value" not in row.client_secret_sealed
            opened = token_vault.open_sealed(row.client_secret_sealed, purpose=purpose)
            assert opened == "synthetic value"
    finally:
        with Session(get_engine()) as session, session.begin():
            row = session.get(GoogleConnection, 1)
            if row is not None:
                session.delete(row)
    with Session(get_engine()) as session:
        assert session.get(GoogleConnection, 1) is None


def test_the_running_stack_refuses_to_store_a_google_client():
    """The CI stack runs in fixture data mode, so the connection routes store nothing.

    Assertions compare status codes and fixed values only, so a failure never prints the code.
    """
    client_body = {
        "client_id": "123456789012-synthetic0client.apps.googleusercontent.com",
        "client_secret": "synthetic-client-secret",
    }
    code = get_settings().setup_code.get_secret_value()
    with httpx.Client(base_url="http://api:8000", timeout=20) as client:
        assert client.get("/api/google/connection").status_code == 401
        assert client.put("/api/google/client", json=client_body).status_code == 401
        assert client.post("/api/session", json={"code": code}).status_code == 204
        try:
            assert client.get("/api/google/connection").json() == {
                "available": False,
                "unavailable_reason": "fixture_mode",
                "client_configured": False,
                "client_id": None,
                "state": "not_configured",
            }
            refused = client.put("/api/google/client", json=client_body)
            assert refused.status_code == 409
            assert client_body["client_secret"] not in refused.text
        finally:
            assert client.delete("/api/session").status_code == 204
    with Session(get_engine()) as session:
        assert session.get(GoogleConnection, 1) is None
