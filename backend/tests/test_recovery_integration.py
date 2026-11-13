"""Durable recovery, claim fencing, and real worker death in isolated schemas."""

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import integration_db
import pytest
import redis
from celery import Celery
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from test_jobs_integration import fixture_stack
from test_jobs_integration import job_store as job_store
from test_profile_integration import profile_database as profile_database

from app.config import get_settings
from app.job_tasks import execute_fetch, fetch_jobs
from app.models import DiagnosticRun, Job, JobFetch
from app.recovery import MAX_DELIVERIES, new_intent, recover_pending, recover_tasks
from app.tasks import run_diagnostic

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1", reason="Requires PostgreSQL and Redis"
)


def make_due(engine, run_id):
    with Session(engine) as session, session.begin():
        run = session.get(JobFetch, run_id)
        run.last_dispatched_at = datetime.now(UTC) - timedelta(minutes=3)
        if run.lease_expires_at:
            run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)


def test_commit_without_publication_is_recovered_with_same_id(job_store):
    engine, client, _ = job_store
    run_id = UUID(client.post("/api/job-fetches", json={"source": "adzuna"}).json()["id"])
    make_due(engine, run_id)

    def publish(task, task_id, kwargs):
        assert task == fetch_jobs and task_id == run_id and kwargs == {}
        with Session(engine) as session:
            assert session.get(JobFetch, run_id).delivery_attempts == 2
        execute_fetch(task_id, "worker@recovered")

    recover_pending(engine, publish)
    with Session(engine) as session:
        run = session.get(JobFetch, run_id)
        assert run.status == "succeeded" and run.worker == "worker@recovered"
        assert len(session.scalars(select(Job)).all()) == 2
    publisher = MagicMock()
    recover_pending(engine, publisher, now=datetime.now(UTC) + timedelta(hours=1))
    publisher.assert_not_called()


def test_broker_failure_remains_pending_and_lost_ack_cannot_overwrite_success(job_store):
    engine, client, publisher = job_store
    publisher.side_effect = ConnectionError("private")
    assert client.post("/api/job-fetches", json={"source": "adzuna"}).status_code == 503
    row = client.get("/api/job-fetches/latest?source=adzuna").json()
    run_id = UUID(row["id"])
    assert client.post("/api/job-fetches", json={"source": "adzuna"}).status_code == 409
    make_due(engine, run_id)

    def ambiguous_ack(task, task_id, kwargs):
        execute_fetch(task_id, "worker@ack-lost")
        raise ConnectionError("ack lost")

    recover_pending(engine, ambiguous_ack)
    with Session(engine) as session:
        run = session.get(JobFetch, run_id)
        assert run.status == "succeeded" and run.error_message is None


@pytest.mark.parametrize("model", [DiagnosticRun, JobFetch])
def test_recovery_budget_and_deadline_end_in_durable_failure(profile_database, model):
    engine, _ = profile_database
    now = datetime.now(UTC)
    run_id, expired_id = uuid4(), uuid4()
    extra = {"source": "manual"} if model is DiagnosticRun else {"source": "adzuna", "query": {}}
    with Session(engine) as session, session.begin():
        session.add(model(id=run_id, status="queued", **extra, **new_intent()))
    publisher = MagicMock()
    for _ in range(MAX_DELIVERIES):
        now += timedelta(seconds=61)
        recover_pending(engine, publisher, now=now)
    assert publisher.call_count == MAX_DELIVERIES - 1
    with Session(engine) as session, session.begin():
        run = session.get(model, run_id)
        assert run.status == "failed" and run.completed_at and run.error_message
        assert run.delivery_attempts == MAX_DELIVERIES
        session.add(
            model(
                id=expired_id,
                status="queued",
                **extra,
                recovery_deadline=now - timedelta(seconds=1),
                delivery_attempts=1,
            )
        )
    publisher.reset_mock()
    recover_pending(engine, publisher, now=now)
    publisher.assert_not_called()
    with Session(engine) as session:
        assert session.get(model, expired_id).status == "failed"


def test_old_work_is_not_replayed_and_old_failure_history_cannot_starve_new_work(profile_database):
    engine, _ = profile_database
    old_id, new_id = uuid4(), uuid4()
    with Session(engine) as session, session.begin():
        session.add(
            JobFetch(
                id=old_id,
                source="adzuna",
                status="running",
                query={},
                created_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
        for _ in range(101):
            session.add(
                DiagnosticRun(
                    id=uuid4(),
                    source="manual",
                    status="publish_failed",
                    created_at=datetime.now(UTC) - timedelta(hours=1),
                )
            )
        session.add(
            DiagnosticRun(
                id=new_id,
                source="manual",
                status="queued",
                recovery_deadline=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
    publisher = MagicMock()
    recover_pending(engine, publisher)
    assert publisher.call_count == 1 and publisher.call_args.args[1] == new_id
    with Session(engine) as session:
        run = session.get(JobFetch, old_id)
        assert run.status == "failed" and run.error_code == "legacy_expired"


def test_migration_preserves_history_without_enrolling_legacy_requests(profile_database):
    engine, schema = profile_database
    run_id, fetch_id = uuid4(), uuid4()
    integration_db.migrate_schema(schema, operation="downgrade", target="0007")
    owner = integration_db.owner_engine(schema)
    with owner.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO diagnostic_runs (id,source,status,result) "
                "VALUES (:id,'manual','succeeded','{\"message\":\"preserved\"}'::jsonb)"
            ),
            {"id": run_id},
        )
        connection.execute(
            text(
                "INSERT INTO job_fetches (id,source,status,query) "
                "VALUES (:id,'adzuna','queued','{\"what\":\"Original query\"}'::jsonb)"
            ),
            {"id": fetch_id},
        )
    owner.dispose()
    integration_db.migrate_schema(schema)
    with Session(engine) as session:
        diagnostic = session.get(DiagnosticRun, run_id)
        fetch = session.get(JobFetch, fetch_id)
        assert diagnostic.status == "succeeded" and diagnostic.result == {"message": "preserved"}
        assert fetch.status == "queued" and fetch.query == {"what": "Original query"}
        assert fetch.recovery_deadline is None and fetch.delivery_attempts == 0
    publisher = MagicMock()
    recover_pending(engine, publisher)
    publisher.assert_not_called()


def test_terminal_failure_rejects_late_worker_delivery(job_store, monkeypatch):
    engine, client, _ = job_store
    run_id = UUID(client.post("/api/job-fetches", json={"source": "adzuna"}).json()["id"])
    make_due(engine, run_id)
    with Session(engine) as session, session.begin():
        session.get(JobFetch, run_id).recovery_deadline = datetime.now(UTC) - timedelta(seconds=1)
    recover_pending(engine, MagicMock())
    before = client.get(f"/api/job-fetches/{run_id}").json()
    assert before["status"] == "failed"
    fetch = MagicMock()
    monkeypatch.setattr("app.job_tasks.fetch_and_store", fetch)
    execute_fetch(run_id, "worker@late")
    fetch.assert_not_called()
    assert client.get(f"/api/job-fetches/{run_id}").json() == before


def test_overlapping_recovery_sweeps_publish_once(job_store):
    engine, client, _ = job_store
    run_id = UUID(client.post("/api/job-fetches", json={"source": "adzuna"}).json()["id"])
    make_due(engine, run_id)
    entered, release = Event(), Event()

    def slow_publish(*args):
        entered.set()
        assert release.wait(10)

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(recover_pending, engine, slow_publish)
        try:
            assert entered.wait(5)
            second = MagicMock()
            recover_pending(engine, second)
            second.assert_not_called()
        finally:
            release.set()
        first.result(timeout=5)
    with Session(engine) as session:
        assert session.get(JobFetch, run_id).delivery_attempts == 2


def test_active_claim_blocks_duplicate_execution_and_reconciliation(job_store, monkeypatch):
    engine, client, _ = job_store
    run_id = UUID(client.post("/api/job-fetches", json={"source": "adzuna"}).json()["id"])
    make_due(engine, run_id)
    entered, release = Event(), Event()
    from app.job_tasks import normalize_response

    def blocked(payload):
        entered.set()
        assert release.wait(10)
        return normalize_response(payload)

    normalize = MagicMock(side_effect=blocked)
    monkeypatch.setattr("app.job_tasks.normalize_response", normalize)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(execute_fetch, run_id, "worker@first")
        try:
            assert entered.wait(5)
            execute_fetch(run_id, "worker@duplicate")
            publisher = MagicMock()
            recover_pending(engine, publisher)
            publisher.assert_not_called()
            assert normalize.call_count == 1
        finally:
            release.set()
        first.result(timeout=5)
    with Session(engine) as session:
        assert session.get(JobFetch, run_id).worker == "worker@first"


@pytest.mark.parametrize("stale_error", [False, True])
def test_expired_claim_fences_stale_results_and_errors(job_store, monkeypatch, stale_error):
    engine, client, _ = job_store
    run_id = UUID(client.post("/api/job-fetches", json={"source": "adzuna"}).json()["id"])
    entered, release = Event(), Event()
    from app.job_tasks import normalize_response

    calls = 0

    def blocked_first(payload):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            assert release.wait(10)
            if stale_error:
                raise ValueError("stale private failure")
        return normalize_response(payload)

    monkeypatch.setattr("app.job_tasks.normalize_response", blocked_first)
    with ThreadPoolExecutor(max_workers=1) as pool:
        stale = pool.submit(execute_fetch, run_id, "worker@stale")
        try:
            assert entered.wait(5)
            make_due(engine, run_id)
            recover_pending(engine, MagicMock())
            execute_fetch(run_id, "worker@replacement")
            before = client.get(f"/api/job-fetches/{run_id}").json()
            assert before["status"] == "succeeded"
        finally:
            release.set()
        stale.result(timeout=5)
    assert client.get(f"/api/job-fetches/{run_id}").json() == before
    assert before["worker"] == "worker@replacement" and before["error_message"] is None


@fixture_stack
def test_real_worker_death_and_unpublished_intent_recover_via_broker(profile_database):
    engine, schema = profile_database
    fetch_id, diagnostic_id = uuid4(), uuid4()
    with Session(engine) as session, session.begin():
        session.add(
            JobFetch(
                id=fetch_id,
                source="adzuna",
                status="queued",
                query={"what": "Head of QA", "where": "Example City"},
                **new_intent(),
            )
        )
        intent = new_intent()
        intent["last_dispatched_at"] -= timedelta(minutes=3)
        session.add(DiagnosticRun(id=diagnostic_id, source="manual", status="queued", **intent))
    queue = f"nextup_recovery_test_{uuid4().hex}"
    prefix = queue + ":"
    test_app = Celery(
        "recovery-test",
        broker=get_settings().redis_url,
        broker_transport_options={"global_keyprefix": prefix},
    )
    code = (
        integration_db.SUBPROCESS_ENGINE
        + """
import time
from app.celery_app import celery_app
celery_app.conf.task_default_queue=os.environ['NEXTUP_TEST_QUEUE']
celery_app.conf.broker_transport_options={**celery_app.conf.broker_transport_options,
    'global_keyprefix':os.environ['NEXTUP_TEST_QUEUE']+':'}
if os.environ['NEXTUP_TEST_BLOCK']=='1':
    import app.job_tasks
    app.job_tasks.fetch_and_store=lambda *args:time.sleep(300)
celery_app.worker_main(['worker','--pool=solo','--loglevel=ERROR','--without-gossip',
    '--without-mingle','--without-heartbeat','-Q',os.environ['NEXTUP_TEST_QUEUE'],
    '--hostname=recovery-test@%h'])
"""
    )

    def start(block):
        return subprocess.Popen(
            [sys.executable, "-c", code],
            env=integration_db.schema_runtime_environment(
                schema, NEXTUP_TEST_QUEUE=queue, NEXTUP_TEST_BLOCK=str(block)
            ),
        )

    def wait(model, run_id, status):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            assert process.poll() is None
            with Session(engine) as session:
                row = session.get(model, run_id)
                if row is not None and row.status == status:
                    return
            time.sleep(0.2)
        pytest.fail(f"Isolated worker did not reach {status}")

    process = start(1)
    try:
        test_app.send_task(fetch_jobs.name, task_id=str(fetch_id), queue=queue, retry=False)
        wait(JobFetch, fetch_id, "running")
        process.kill()  # Only the isolated test child; never the working service.
        process.wait(timeout=5)
        make_due(engine, fetch_id)  # Advance the lease clock; do not sleep two minutes.
        process = start(0)
        test_app.send_task(recover_tasks.name, queue=queue, retry=False)
        wait(JobFetch, fetch_id, "succeeded")
        wait(DiagnosticRun, diagnostic_id, "succeeded")
        with Session(engine) as session:
            row = session.get(JobFetch, fetch_id)
            completed = row.completed_at
            assert row.worker.startswith("recovery-test@") and row.delivery_attempts == 2
            assert len(session.scalars(select(Job)).all()) == 2
        test_app.send_task(fetch_jobs.name, task_id=str(fetch_id), queue=queue, retry=False)
        sentinel = uuid4()
        test_app.send_task(
            run_diagnostic.name,
            task_id=str(sentinel),
            kwargs={"source": "scheduler"},
            queue=queue,
            retry=False,
        )
        wait(DiagnosticRun, sentinel, "succeeded")
        with Session(engine) as session:
            assert session.get(JobFetch, fetch_id).completed_at == completed
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        test_app.close()
        with redis.Redis.from_url(get_settings().redis_url) as broker:
            keys = list(broker.scan_iter(match=prefix + "*"))
            if keys:
                broker.delete(*keys)  # Only this test's isolated namespace, including unacked work.
