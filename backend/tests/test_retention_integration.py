"""Deletion tests use temporary PostgreSQL schemas, never working user history."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from test_profile_integration import EXAMPLE
from test_profile_integration import profile_client as profile_client
from test_profile_integration import profile_database as profile_database

from app import retention
from app.config import Settings, get_settings
from app.job_tasks import execute_fetch
from app.main import app
from app.models import DiagnosticRun, Job, JobAlert, JobFetch, SavedSearch
from app.tasks import run_diagnostic

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1", reason="Requires running PostgreSQL"
)
NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)
OLD = NOW - timedelta(days=40)
BASE = "/api/task-history"


@pytest.fixture(autouse=True)
def policy(monkeypatch):
    settings = Settings(task_history_cleanup_enabled=True)
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr(retention, "now", lambda: NOW)
    yield settings
    app.dependency_overrides.pop(get_settings, None)


def row(model=DiagnosticRun, **values):
    defaults = dict(
        id=uuid4(),
        source="manual" if model is DiagnosticRun else "adzuna",
        status="succeeded",
        created_at=OLD,
        completed_at=OLD,
    )
    if model is JobFetch:
        defaults["query"] = {}
    return model(**{**defaults, **values})


def seed(engine, *rows):
    # Add newer anchors so age-eligible records are not protected as latest per source.
    with Session(engine, expire_on_commit=False) as session, session.begin():
        session.add_all(
            [
                row(created_at=NOW, completed_at=NOW),
                row(JobFetch, created_at=NOW, completed_at=NOW),
                *rows,
            ]
        )


def preview(client):
    response = client.get(f"{BASE}/preview")
    assert response.status_code == 200, response.text
    return response.json()


def cleanup(client, token, **extra):
    return client.post(
        f"{BASE}/cleanup",
        json={
            "token": token,
            "confirmation": "delete_completed_task_history",
            **extra,
        },
    )


def test_policy_defaults_and_bounds():
    assert Settings(task_history_cleanup_enabled=False).task_history_cleanup_enabled is False
    assert Settings.model_fields["task_history_cleanup_enabled"].default is False
    for field, value in [
        ("task_history_retention_days", 6),
        ("task_history_retention_days", 3651),
        ("task_history_batch_size", 0),
        ("task_history_batch_size", 501),
    ]:
        with pytest.raises(ValidationError):
            Settings(**{field: value})


def test_preview_exclusions_and_read_only(profile_client, profile_database, policy):
    policy.task_history_cleanup_enabled = False
    good = row()
    failed = row(JobFetch, status="failed")
    excluded = [
        row(status="queued"),
        row(status="publish_failed"),
        row(completed_at=None),
        row(completed_at=NOW - timedelta(days=30)),
        row(completed_at=NOW),
        row(source="scheduler"),  # newest source record is protected even when old
        row(JobFetch, status="running"),
        row(JobFetch, status="publish_failed"),
        row(JobFetch, completed_at=None),
        row(JobFetch, execution_token=uuid4()),
        row(JobFetch, lease_expires_at=OLD),
    ]
    seed(profile_database[0], good, failed, *excluded)
    result = preview(profile_client)
    assert result["enabled"] is False
    assert result["groups"]["diagnostics"]["items"][0]["id"] == str(good.id)
    assert result["groups"]["fetches"]["items"][0]["id"] == str(failed.id)
    assert all(group["eligible"] == group["selected"] == 1 for group in result["groups"].values())
    assert cleanup(profile_client, result["token"]).status_code == 403
    with Session(profile_database[0]) as session:
        assert len(session.scalars(select(DiagnosticRun)).all()) == 8
        assert len(session.scalars(select(JobFetch)).all()) == 7


def test_batch_exact_ids_replay_and_late_delivery(
    profile_client, profile_database, policy, monkeypatch
):
    policy.task_history_batch_size = 1
    first, second, fetch = row(completed_at=OLD - timedelta(days=1)), row(), row(JobFetch)
    seed(profile_database[0], first, second, fetch)
    result = preview(profile_client)
    assert result["groups"]["diagnostics"]["eligible"] == 2
    assert result["groups"]["diagnostics"]["selected"] == 1
    # A newly eligible candidate after preview cannot be included by cleanup.
    with Session(profile_database[0]) as session, session.begin():
        session.add(row(completed_at=OLD - timedelta(days=2)))
    response = cleanup(profile_client, result["token"])
    assert response.status_code == 200, response.text
    assert response.json()["groups"] == {
        "diagnostics": {"deleted": 1, "skipped": 0},
        "fetches": {"deleted": 1, "skipped": 0},
    }
    assert all(
        v == {"deleted": 0, "skipped": 1}
        for v in cleanup(profile_client, result["token"]).json()["groups"].values()
    )
    monkeypatch.setattr("app.tasks.get_engine", lambda: profile_database[0])
    monkeypatch.setattr("app.job_tasks.get_engine", lambda: profile_database[0])
    monkeypatch.setattr(
        "app.job_tasks.fetch_and_store", lambda *args: pytest.fail("Deleted work executed")
    )
    run_diagnostic.apply(task_id=str(first.id), kwargs={"source": "manual"}, throw=True)
    execute_fetch(fetch.id, "late-worker")
    with Session(profile_database[0]) as session:
        assert session.get(DiagnosticRun, first.id) is None
        assert session.get(JobFetch, fetch.id) is None
        assert len(session.scalars(select(DiagnosticRun)).all()) == 3


def test_confirmation_signature_expiry_and_policy(
    profile_client, profile_database, policy, monkeypatch
):
    seed(profile_database[0], row())
    token = preview(profile_client)["token"]
    assert profile_client.post(f"{BASE}/cleanup", json={"token": token}).status_code == 422
    assert cleanup(profile_client, token, confirmation="yes").status_code == 422
    assert cleanup(profile_client, token, additional_ids=[]).status_code == 422
    assert cleanup(profile_client, token + "x").status_code == 409
    policy.task_history_retention_days = 31
    assert cleanup(profile_client, token).status_code == 409
    policy.task_history_retention_days = 30
    policy.task_history_batch_size = 2
    assert cleanup(profile_client, token).status_code == 409
    policy.task_history_batch_size = 100
    monkeypatch.setattr(retention, "now", lambda: NOW + timedelta(minutes=10))
    assert cleanup(profile_client, token).status_code == 409
    with Session(profile_database[0]) as session:
        assert len(session.scalars(select(DiagnosticRun)).all()) == 2


def test_changed_and_locked_rows_are_skipped(profile_client, profile_database):
    changed, locked, claimed = row(), row(), row(JobFetch)
    seed(profile_database[0], changed, locked, claimed)
    token = preview(profile_client)["token"]
    with Session(profile_database[0]) as session, session.begin():
        session.get(DiagnosticRun, changed.id).status = "queued"
        session.get(JobFetch, claimed.id).execution_token = uuid4()
    with Session(profile_database[0]) as locker, locker.begin():
        locker.scalar(select(DiagnosticRun).where(DiagnosticRun.id == locked.id).with_for_update())
        result = cleanup(profile_client, token)
        assert result.status_code == 200, result.text
        assert result.json()["groups"] == {
            "diagnostics": {"deleted": 0, "skipped": 2},
            "fetches": {"deleted": 0, "skipped": 1},
        }
    # The same preview may delete its now-unlocked eligible row, never other rows.
    assert cleanup(profile_client, token).json()["groups"]["diagnostics"] == {
        "deleted": 1,
        "skipped": 1,
    }


def test_saved_data_preserved_and_both_tables_atomic(profile_client, profile_database, monkeypatch):
    assert profile_client.put("/api/profile", json=EXAMPLE).status_code == 200
    seed(profile_database[0], row(), row(JobFetch))
    search_id = uuid4()
    with Session(profile_database[0]) as session, session.begin():
        session.add(
            Job(
                source="adzuna",
                external_id="retention-test",
                title="Synthetic role",
                company="Example",
                location="Example",
                description="Synthetic",
                url="https://example.test",
                posted_at=OLD,
                dedupe_key="synthetic",
            )
        )
        session.add(
            SavedSearch(
                id=search_id, name="Synthetic", name_key="synthetic", source="adzuna", filters={}
            )
        )
        session.flush()
        session.add(
            JobAlert(
                id=uuid4(),
                search_id=search_id,
                job_key="synthetic",
                search_name="Synthetic",
                job={},
            )
        )

    def snapshot():
        with profile_database[0].connect() as connection:
            return {
                table: connection.execute(text(f"SELECT row_to_json(t)::text FROM {table} t"))
                .scalars()
                .all()
                for table in ("profiles", "jobs", "saved_searches", "job_alerts")
            }

    before = snapshot()
    token = preview(profile_client)["token"]
    original = Session.delete

    def fail_second_table(self, instance):
        if isinstance(instance, JobFetch):
            raise RuntimeError("synthetic rollback")
        return original(self, instance)

    with monkeypatch.context() as patch:
        patch.setattr(Session, "delete", fail_second_table)
        with pytest.raises(RuntimeError, match="synthetic rollback"):
            cleanup(profile_client, token)
    with Session(profile_database[0]) as session:
        assert len(session.scalars(select(DiagnosticRun)).all()) == 2
        assert len(session.scalars(select(JobFetch)).all()) == 2
    assert cleanup(profile_client, token).status_code == 200
    assert snapshot() == before


def test_old_latest_per_source_and_changed_completion_are_preserved(
    profile_client, profile_database
):
    # All old records qualify by age, but the deterministic newest for each source stays.
    older = row(created_at=OLD - timedelta(days=1))
    latest = row()
    other_source = row(source="scheduler")
    fetch = row(JobFetch)
    with Session(profile_database[0], expire_on_commit=False) as session, session.begin():
        session.add_all([older, latest, other_source, fetch])
    result = preview(profile_client)
    assert result["groups"]["diagnostics"]["selected"] == 1
    assert result["groups"]["diagnostics"]["items"][0]["id"] == str(older.id)
    assert result["groups"]["fetches"]["selected"] == 0
    # An eligible record becomes recently completed between preview and execution.
    with Session(profile_database[0]) as session, session.begin():
        session.get(DiagnosticRun, older.id).completed_at = NOW
    assert cleanup(profile_client, result["token"]).json()["groups"]["diagnostics"] == {
        "deleted": 0,
        "skipped": 1,
    }
    with Session(profile_database[0]) as session:
        assert len(session.scalars(select(DiagnosticRun)).all()) == 3
        assert session.get(JobFetch, fetch.id) is not None


def test_restart_invalidates_preview_without_deletion(
    profile_client, profile_database, monkeypatch
):
    seed(profile_database[0], row())
    token = preview(profile_client)["token"]
    monkeypatch.setattr(retention, "signing_key", lambda: b"new-process-key")
    assert cleanup(profile_client, token).status_code == 409
    with Session(profile_database[0]) as session:
        assert len(session.scalars(select(DiagnosticRun)).all()) == 2
