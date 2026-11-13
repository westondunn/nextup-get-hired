"""Local alerts in isolated PostgreSQL; no external notification delivery."""

import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import integration_db
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from test_jobs_integration import job_store as job_store
from test_jobs_integration import remove_profile
from test_profile_integration import profile_database as profile_database
from test_scoring_integration import PROFILE, add_job

from app.alert_tasks import check_alerts, evaluate_alerts
from app.celery_app import celery_app
from app.models import Job, JobAlert, Profile, SavedSearch

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1", reason="Requires running Compose services"
)


@pytest.fixture
def alert_store(job_store, monkeypatch):
    engine, client, _ = job_store
    monkeypatch.setattr("app.alert_tasks.get_engine", lambda: engine)
    publisher = MagicMock()
    monkeypatch.setattr("app.alerts.check_alerts.apply_async", publisher)
    return engine, client, publisher


def saved_search(client, **changes):
    response = client.post(
        "/api/saved-searches", json={"name": "QA alerts", "source": "all", **changes}
    )
    assert response.status_code == 201
    return response.json()["id"]


def enable(client, search_id, minimum=0):
    response = client.put(
        f"/api/saved-searches/{search_id}/alerts", json={"enabled": True, "min_score": minimum}
    )
    assert response.status_code == 200
    return response.json()


def test_opt_in_requires_profile_and_does_not_fetch_or_publish(alert_store):
    engine, client, publisher = alert_store
    remove_profile(engine)
    search_id = saved_search(client)
    assert not client.get(f"/api/saved-searches/{search_id}").json()["alerts_enabled"]
    assert (
        client.put(f"/api/saved-searches/{search_id}/alerts", json={"enabled": True}).status_code
        == 409
    )
    assert client.post(f"/api/saved-searches/{search_id}/alerts/check").status_code == 409
    add_job(engine, "stored")
    evaluate_alerts("worker@test")
    assert client.get("/api/alerts").json() == {"items": [], "total": 0, "unread": 0}
    assert client.put("/api/profile", json=PROFILE).status_code == 200
    enable(client, search_id)
    publisher.assert_not_called()


def test_matching_dedup_read_disable_and_delete_preserve_other_data(alert_store):
    engine, client, _ = alert_store
    client.put("/api/profile", json=PROFILE)
    search_id = saved_search(client)
    add_job(engine, "first")
    add_job(engine, "duplicate", source="greenhouse")
    enable(client, search_id)
    evaluate_alerts("worker@first")
    inbox = client.get("/api/alerts").json()
    assert inbox["total"] == inbox["unread"] == 1
    alert = inbox["items"][0]
    assert len(alert["job"]["origins"]) == 2
    assert alert["search_name"] == "QA alerts"
    evaluate_alerts("worker@replayed")
    assert client.get("/api/alerts").json()["items"] == [alert]
    read = client.put(f"/api/alerts/{alert['id']}/read").json()
    assert read["read_at"] is not None
    assert client.put(f"/api/alerts/{alert['id']}/read").json() == read
    assert client.get("/api/alerts?unread_only=true").json()["total"] == 0
    client.put(f"/api/saved-searches/{search_id}/alerts", json={"enabled": False})
    add_job(engine, "another", title="Other opening")
    evaluate_alerts("worker@disabled")
    assert client.get("/api/alerts").json()["total"] == 1
    enable(client, search_id)
    evaluate_alerts("worker@reenabled")
    assert client.get("/api/alerts").json()["total"] == 2
    assert client.get("/api/alerts").json()["unread"] == 1
    assert client.delete(f"/api/saved-searches/{search_id}").status_code == 204
    assert client.get("/api/alerts").json()["total"] == 0
    assert client.get("/api/profile").json() == PROFILE
    with Session(engine) as session:
        assert len(session.scalars(select(Job)).all()) == 3


@pytest.mark.parametrize("saved_min,alert_min", [(90, 0), (0, 90)])
def test_filters_threshold_expiration_and_batching_precede_notification_limit(
    alert_store, saved_min, alert_min
):
    engine, client, _ = alert_store
    client.put("/api/profile", json=PROFILE)
    search_id = saved_search(
        client, include_expired=True, filters={"min_score": saved_min, "exclude": "intern"}
    )
    for index in range(12):
        add_job(engine, str(index), title=f"Head of QA {index}")
    add_job(engine, "low", description="Unrelated")
    add_job(engine, "excluded", title="Head of QA intern")
    add_job(engine, "old", title="Head of QA expired")
    with Session(engine) as session, session.begin():
        session.get(Job, ("adzuna", "old")).fetched_at = datetime.now(UTC) - timedelta(days=40)
    enable(client, search_id, minimum=alert_min)  # Always use the stricter threshold.
    evaluate_alerts("worker@first")
    assert client.get("/api/alerts").json()["total"] == 10
    evaluate_alerts("worker@second")
    assert client.get("/api/alerts").json()["total"] == 12
    first = client.get("/api/alerts?limit=10").json()
    second = client.get("/api/alerts?offset=10").json()
    assert len(first["items"]) == 10 and len(second["items"]) == 2
    assert all(item["job"]["score"] >= 90 for item in first["items"] + second["items"])
    assert not {item["id"] for item in first["items"]} & {item["id"] for item in second["items"]}


def test_profile_loss_and_updated_queries_do_not_resend_existing_identity(alert_store):
    engine, client, _ = alert_store
    client.put("/api/profile", json=PROFILE)
    search_id = saved_search(client)
    add_job(engine, "first")
    enable(client, search_id)
    with Session(engine) as session, session.begin():
        session.delete(session.get(Profile, 1))
    evaluate_alerts("worker@missing-profile")
    assert (
        client.get(f"/api/saved-searches/{search_id}").json()["alert_check_status"]
        == "profile_required"
    )
    assert client.get("/api/alerts").json()["total"] == 0
    client.put("/api/profile", json=PROFILE)
    evaluate_alerts("worker@restored")
    snapshot = client.get("/api/alerts").json()["items"][0]
    client.put(
        f"/api/saved-searches/{search_id}",
        json={"name": "Renamed", "source": "all", "filters": {"q": "Python"}},
    )
    with Session(engine) as session, session.begin():
        session.get(Job, ("adzuna", "first")).description += " Updated text"
    evaluate_alerts("worker@updated")
    assert client.get("/api/alerts").json()["items"] == [snapshot]


def test_queued_check_and_publish_failure_are_honest(alert_store):
    _, client, publisher = alert_store
    client.put("/api/profile", json=PROFILE)
    search_id = saved_search(client)
    enable(client, search_id)
    path = f"/api/saved-searches/{search_id}/alerts/check"
    assert client.post(path).status_code == 202
    publisher.assert_called_once_with(kwargs={"search_id": search_id}, retry=False)
    assert client.post(path).status_code == 409
    evaluate_alerts("worker@test")
    assert client.get(f"/api/saved-searches/{search_id}").json()["alert_check_status"] == "ok"
    publisher.side_effect = ConnectionError("private details")
    response = client.post(path)
    assert response.status_code == 503 and "private details" not in response.text
    assert (
        client.get(f"/api/saved-searches/{search_id}").json()["alert_check_status"]
        == "publish_failed"
    )
    evaluate_alerts("worker@scheduled-recovery")
    assert client.get(f"/api/saved-searches/{search_id}").json()["alert_check_status"] == "ok"


def test_concurrent_check_skips_locked_search_and_database_suppresses_duplicates(alert_store):
    engine, client, _ = alert_store
    client.put("/api/profile", json=PROFILE)
    search_id = saved_search(client)
    add_job(engine, "one")
    enable(client, search_id)
    with Session(engine) as locked, locked.begin():
        locked.scalar(
            select(SavedSearch).where(SavedSearch.id == UUID(search_id)).with_for_update()
        )
        evaluate_alerts("worker@concurrent")
        assert client.get("/api/alerts").json()["total"] == 0
    evaluate_alerts("worker@after-lock")
    evaluate_alerts("worker@again")
    assert client.get("/api/alerts").json()["total"] == 1


@pytest.mark.parametrize(
    "body",
    [
        {"enabled": "true"},
        {"enabled": True, "min_score": 101},
        {"enabled": True, "min_score": -1},
        {"enabled": True, "min_score": True},
        {"enabled": True, "email": "never@example.invalid"},
    ],
)
def test_invalid_alert_settings_leave_opt_in_off(alert_store, body):
    _, client, _ = alert_store
    search_id = saved_search(client)
    assert client.put(f"/api/saved-searches/{search_id}/alerts", json=body).status_code == 422
    assert not client.get(f"/api/saved-searches/{search_id}").json()["alerts_enabled"]


def test_missing_records_and_invalid_pagination(alert_store):
    _, client, _ = alert_store
    assert client.get(f"/api/saved-searches/{uuid4()}").status_code == 404
    assert (
        client.put(f"/api/saved-searches/{uuid4()}/alerts", json={"enabled": False}).status_code
        == 404
    )
    assert client.put(f"/api/alerts/{uuid4()}/read").status_code == 404
    assert client.get("/api/alerts?limit=51").status_code == 422
    assert client.get("/api/alerts?offset=-1").status_code == 422


def test_migration_preserves_legacy_search_and_leaves_alerts_off(alert_store):
    engine, client, _ = alert_store
    search_id = uuid4()
    integration_db.migrate_engine_schema(engine, operation="downgrade", target="0006")
    owner = integration_db.owner_engine_for(engine)
    try:
        with owner.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO saved_searches(id,name,name_key,source,include_expired,filters) "
                    "VALUES (:id,'Legacy QA','legacy qa','adzuna',true,CAST(:filters AS jsonb))"
                ),
                {"id": search_id, "filters": '{"q":"Python","min_score":40}'},
            )
    finally:
        owner.dispose()
    integration_db.migrate_engine_schema(engine)
    result = client.get(f"/api/saved-searches/{search_id}").json()
    assert result["name"] == "Legacy QA" and result["include_expired"]
    assert result["filters"]["q"] == "Python" and result["filters"]["min_score"] == 40
    assert result["alerts_enabled"] is False and result["alert_min_score"] == 70
    assert result["alert_check_status"] == "disabled" and result["alert_checked_at"] is None


def test_real_broker_worker_alert_persistence_in_isolated_schema(profile_database):
    engine, schema = profile_database
    search_id = uuid4()
    with Session(engine) as session, session.begin():
        session.add(Profile(id=1, **PROFILE))
        session.add(
            SavedSearch(
                id=search_id,
                name="Isolated broker test",
                name_key="isolated broker test",
                source="all",
                include_expired=False,
                filters={},
                alerts_enabled=True,
                alert_min_score=0,
            )
        )
    add_job(engine, "broker")
    queue = f"nextup_alert_test_{uuid4().hex}"
    code = (
        integration_db.SUBPROCESS_ENGINE
        + """
from app.celery_app import celery_app
celery_app.worker_main(['worker', '--pool=solo', '--loglevel=ERROR', '--without-gossip',
    '--without-mingle', '--without-heartbeat', '-Q', os.environ['NEXTUP_TEST_QUEUE'],
    '--hostname=alerts-test@%h'])
"""
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        env=integration_db.schema_runtime_environment(schema, NEXTUP_TEST_QUEUE=queue),
    )
    try:
        check_alerts.apply_async(kwargs={"search_id": str(search_id)}, queue=queue, retry=False)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            assert process.poll() is None
            with Session(engine) as session:
                row = session.get(SavedSearch, search_id)
                if row.alert_check_status == "ok":
                    assert row.alert_worker.startswith("alerts-test@")
                    assert len(session.scalars(select(JobAlert)).all()) == 1
                    break
            time.sleep(0.2)
        else:
            pytest.fail("Isolated worker did not persist an alert through Redis")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        with celery_app.connection_for_write() as connection:
            connection.default_channel.queue_delete(queue)
    assert (
        celery_app.conf.beat_schedule["local-alert-check"]["task"] == "app.alert_tasks.check_alerts"
    )
