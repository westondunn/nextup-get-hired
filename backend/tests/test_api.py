from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db import get_session
from app.main import app
from app.models import DiagnosticRun


@pytest.fixture
def session():
    database = MagicMock()

    def refresh(run):
        run.created_at = datetime.now(UTC)

    database.refresh.side_effect = refresh
    app.dependency_overrides[get_session] = lambda: database
    yield database
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_liveness_has_no_dependency_on_services(client):
    assert client.get("/api/live").json() == {"status": "up"}


@pytest.mark.parametrize("status,code", [("ok", 200), ("degraded", 503)])
def test_health_status_codes(client, monkeypatch, status, code):
    monkeypatch.setattr("app.main.probe_health", lambda: {"status": status})
    assert client.get("/api/health").status_code == code


def test_publish_uses_persisted_id(client, session, monkeypatch):
    publish = MagicMock()
    monkeypatch.setattr("app.main.run_diagnostic.apply_async", publish)
    response = client.post("/api/diagnostics")
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    publish.assert_called_once_with(
        task_id=response.json()["id"], kwargs={"source": "manual"}, retry=False
    )
    session.commit.assert_called_once()


def test_database_failure_does_not_publish(client, session, monkeypatch):
    session.commit.side_effect = OperationalError("insert", {}, Exception("unavailable"))
    publish = MagicMock()
    monkeypatch.setattr("app.main.run_diagnostic.apply_async", publish)
    response = client.post("/api/diagnostics")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    publish.assert_not_called()


def test_publish_failure_is_reported_and_recorded(client, session, monkeypatch):
    publish = MagicMock(side_effect=ConnectionError("broker unavailable"))
    monkeypatch.setattr("app.main.run_diagnostic.apply_async", publish)
    response = client.post("/api/diagnostics")
    assert response.status_code == 503
    assert "id" in response.json()["detail"]
    assert session.commit.call_count == 2
    statement = session.execute.call_args.args[0]
    assert "queued" in statement.compile().params.values()
    assert "publish_failed" in statement.compile().params.values()


def test_get_missing_diagnostic(client, session):
    session.get.return_value = None
    assert client.get(f"/api/diagnostics/{uuid4()}").status_code == 404


def test_invalid_diagnostic_id(client, session):
    assert client.get("/api/diagnostics/not-a-uuid").status_code == 422
    session.get.assert_not_called()


def test_get_persisted_result(client, session):
    run_id = uuid4()
    session.get.return_value = DiagnosticRun(
        id=run_id,
        source="manual",
        status="succeeded",
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        worker="worker@test",
        result={"database": "test", "message": "Worker reached PostgreSQL"},
    )
    result = client.get(f"/api/diagnostics/{run_id}").json()
    assert result["worker"] == "worker@test"
    assert result["status"] == "succeeded"
