"""Synthetic discovery storage and scheduling; public HTTP is always mocked."""

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4

import integration_db
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from test_profile_integration import profile_client as profile_client
from test_profile_integration import profile_database as profile_database

from app.config import Settings
from app.discovery import enqueue_discovery
from app.employer_catalog import MAX_BOARDS
from app.job_tasks import execute_fetch
from app.models import DiscoverySettings, Job, JobFetch, Profile
from app.sources.common import NormalizedJob

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1", reason="Requires PostgreSQL"
)
# Preferences the API fills in when a client omits them.
DEFAULT_RULES = {
    "needs_sponsorship": False,
    "has_clearance": False,
    "responsibility": "auto",
    "title_aliases": {},
    "other_specialties": [],
}
BOARDS = [
    {"provider": "greenhouse", "board": "example-a", "company": "Example A"},
    {"provider": "greenhouse", "board": "example-b", "company": "Example B"},
    {"provider": "lever", "board": "example-c", "company": "Example C"},
]
PROFILE = {
    "skills": ["Python", "Test automation"],
    "target_titles": ["Director of Quality Engineering"],
    "location": "Synthetic City",
    "work_preferences": ["remote"],
}


@pytest.fixture
def discovery(profile_database, profile_client, monkeypatch):
    engine = profile_database[0]
    settings = Settings(live_job_fetch_enabled=True)
    for module in ("app.discovery", "app.discovery_api", "app.job_tasks"):
        monkeypatch.setattr(module + ".get_settings", lambda: settings)
    monkeypatch.setattr("app.discovery_api.get_engine", lambda: engine)
    monkeypatch.setattr("app.job_tasks.get_engine", lambda: engine)
    assert profile_client.put("/api/profile", json=PROFILE).status_code == 200
    assert (
        profile_client.put("/api/discovery", json={"enabled": True, "boards": BOARDS}).status_code
        == 200
    )
    return engine, profile_client, settings


def test_durable_per_board_intents_cooldown_and_profile_privacy(discovery):
    engine, client, _ = discovery
    publish = Mock()
    rows = enqueue_discovery(engine, publisher=publish)
    assert len(rows) == publish.call_count == 3
    assert enqueue_discovery(engine, publisher=publish) == []
    with Session(engine) as session:
        runs = session.scalars(select(JobFetch)).all()
        assert len(runs) == 3
        assert all(run.recovery_deadline and run.delivery_attempts == 1 for run in runs)
        assert all(set(run.query) == {"board", "company", "discovery", "automatic"} for run in runs)
    assert client.get("/api/discovery").json()["states"][0]["run"]["status"] == "queued"
    # Multi-employer work must not masquerade as the legacy configured-board fetch.
    assert client.get("/api/job-fetches/latest?source=greenhouse").json() is None


def expanded_boards():
    return BOARDS + [
        {"provider": "greenhouse", "board": f"synthetic-{n}", "company": f"Synthetic {n}"}
        for n in range(MAX_BOARDS - len(BOARDS))
    ]


def test_expanded_selection_preserves_rules_schedule_and_rejects_overflow(discovery):
    engine, client, _ = discovery
    before = client.get("/api/discovery").json()
    rules = {"locations": ["US"], "leadership": "strict", "include_unspecified_location": False}
    body = {"enabled": True, "boards": expanded_boards(), "match_preferences": rules}
    response = client.put("/api/discovery", json=body)
    assert response.status_code == 200
    saved = response.json()
    assert len(saved["boards"]) == saved["max_boards"] == MAX_BOARDS
    assert saved["next_run_at"] == before["next_run_at"]
    assert saved["match_preferences"] == {**DEFAULT_RULES, **rules}
    assert len(saved["states"]) == MAX_BOARDS
    overflow = body["boards"] + [{"provider": "lever", "board": "overflow", "company": "Extra"}]
    assert client.put("/api/discovery", json={**body, "boards": overflow}).status_code == 422
    assert client.get("/api/discovery").json()["boards"] == body["boards"]
    with Session(engine) as session:
        assert not session.scalars(select(JobFetch)).all()  # Saving never starts a fetch.


def test_broker_failure_is_saved_and_recovers_original_board_intent(discovery, monkeypatch):
    engine, client, _ = discovery
    rows = enqueue_discovery(engine, publisher=Mock(side_effect=ConnectionError("private")))
    assert all(r["status"] == "publish_failed" for r in rows)
    assert "private" not in client.get("/api/discovery").text
    with Session(engine) as session:
        assert all(r.recovery_deadline for r in session.scalars(select(JobFetch)).all())


def test_worker_filters_locally_upserts_and_does_not_send_profile(discovery, monkeypatch):
    engine, client, _ = discovery
    rows = enqueue_discovery(engine, publisher=Mock())
    job = NormalizedJob(
        external_id="example-a:1",
        title="Director of Quality Engineering",
        company="Example A",
        location="US Remote",
        description="Python test automation",
        url="https://example.invalid/1",
        posted_at=datetime.now(UTC),
    )
    feed = Mock(
        return_value=(
            [
                job,
                job.model_copy(
                    update={
                        "external_id": "example-a:2",
                        "title": "Sales assistant",
                        "description": "Sales",
                    }
                ),
            ],
            2,
            0,
        )
    )
    monkeypatch.setattr("app.sources.employer_boards.fetch_board", feed)
    execute_fetch(UUID(rows[0]["id"]), "worker@synthetic")
    execute_fetch(UUID(rows[0]["id"]), "worker@duplicate")
    assert feed.call_count == 1
    assert feed.call_args.args[:3] == ("greenhouse", "example-a", "Example A")
    result = client.get("/api/jobs?source=all").json()
    assert result["total"] == 1 and result["items"][0]["score"] > 20
    run = client.get("/api/discovery").json()["states"][0]["run"]
    assert run["stored"] == 1 and run["received"] == 2 and run["status"] == "succeeded"


def test_scheduler_due_time_pause_and_removed_employer_prevent_network(discovery, monkeypatch):
    engine, client, settings = discovery
    rows = enqueue_discovery(engine, automatic=True, publisher=Mock())
    assert len(rows) == 3
    assert enqueue_discovery(engine, automatic=True, publisher=Mock()) == []
    assert (
        client.put("/api/discovery", json={"enabled": False, "boards": BOARDS}).status_code == 200
    )
    assert enqueue_discovery(engine, automatic=True, publisher=Mock()) == []
    feed = Mock(side_effect=AssertionError("Must not fetch paused automatic work"))
    monkeypatch.setattr("app.sources.employer_boards.fetch_board", feed)
    execute_fetch(UUID(rows[0]["id"]), "worker@paused")
    feed.assert_not_called()
    with Session(engine) as session:
        assert session.get(JobFetch, UUID(rows[0]["id"])).error_code == "discovery_paused"
    settings.live_job_fetch_enabled = False
    assert enqueue_discovery(engine, automatic=True, publisher=Mock()) == []


def test_config_validation_demo_profile_and_reference_import(discovery):
    engine, client, settings = discovery
    for body in (
        {"enabled": True, "boards": []},
        {"boards": BOARDS * 4},
        {"boards": [BOARDS[0], BOARDS[0]]},
        {"boards": [{**BOARDS[0], "board": "https://localhost/"}]},
    ):
        assert client.put("/api/discovery", json=body).status_code == 422
    settings.live_job_fetch_enabled = False
    assert client.put("/api/discovery", json={"enabled": True, "boards": BOARDS}).status_code == 409
    settings.live_job_fetch_enabled = True
    assert (
        client.put("/api/profile", json={**PROFILE, "location": "Example City"}).status_code == 200
    )
    assert client.post("/api/discovery/run").status_code == 409
    reference = {
        "title": "Synthetic Director",
        "company": "Example",
        "location": "US Remote",
        "description": "User-supplied reference",
        "url": "https://example.invalid/reference",
    }
    first = client.post("/api/job-references", json=reference)
    assert first.status_code == 201
    assert client.post("/api/job-references", json=reference).json() == first.json()
    assert (
        client.post(
            "/api/job-references", json={**reference, "url": "javascript:alert(1)"}
        ).status_code
        == 422
    )
    with Session(engine) as session:
        jobs = session.scalars(select(Job)).all()
        assert len(jobs) == 1 and jobs[0].date_kind == "observed"
        assert session.get(Profile, 1).location == "Example City"


def test_concurrent_scheduler_lock_skips_and_retention_preserves_each_board(discovery):
    engine, client, _ = discovery
    with Session(engine) as locker, locker.begin():
        locker.get(DiscoverySettings, 1, with_for_update=True)
        assert enqueue_discovery(engine, automatic=True, publisher=Mock()) == []
    old = datetime.now(UTC) - timedelta(days=40)
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                JobFetch(
                    id=uuid4(),
                    source="greenhouse",
                    board_key=b["board"],
                    query={},
                    status="succeeded",
                    created_at=old,
                    completed_at=old,
                )
                for b in BOARDS[:2]
            ]
        )
    preview = client.get("/api/task-history/preview").json()
    assert preview["groups"]["fetches"]["eligible"] == 0
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM job_fetches")) == 2


def test_real_broker_discovery_sweep_queues_and_worker_persists_matches(
    discovery, profile_database
):
    import subprocess
    import sys
    import time

    import redis
    from celery import Celery

    from app.config import get_settings

    engine, client, _ = discovery
    assert (
        client.put(
            "/api/discovery", json={"enabled": True, "boards": expanded_boards()}
        ).status_code
        == 200
    )
    queue = f"nextup_discovery_test_{uuid4().hex}"
    code = (
        integration_db.SUBPROCESS_ENGINE
        + """
from datetime import UTC,datetime
from app.sources.common import NormalizedJob
import app.sources.employer_boards
def fixture(provider,board,company,settings):
    return [NormalizedJob(external_id=board+':synthetic',title='Director of Quality Engineering',
        company=company,location='US Remote',description='Python test automation',
        url='https://example.invalid/synthetic',posted_at=datetime.now(UTC))],1,0
app.sources.employer_boards.fetch_board=fixture
from app.celery_app import celery_app
celery_app.conf.task_default_queue=os.environ['NEXTUP_TEST_QUEUE']
celery_app.conf.broker_transport_options={**celery_app.conf.broker_transport_options,
    'global_keyprefix':os.environ['NEXTUP_TEST_QUEUE']+':'}
celery_app.worker_main(['worker','--pool=solo','--loglevel=ERROR','--without-gossip',
    '--without-mingle','--without-heartbeat','-Q',os.environ['NEXTUP_TEST_QUEUE'],
    '--hostname=discovery-test@%h'])
"""
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        # Fixture data mode (the CI default) excludes the live switch (NXG-C17) and would serve
        # bundled listings instead of the stubbed fetcher above, so this one worker leaves it.
        # Nothing real is fetched: fetch_board is replaced in the subprocess.
        env=integration_db.schema_runtime_environment(
            profile_database[1],
            NEXTUP_FIXTURE_DATA_MODE="false",
            NEXTUP_LIVE_JOB_FETCH_ENABLED="true",
            NEXTUP_TEST_QUEUE=queue,
        ),
    )
    broker = Celery(
        "discovery-test",
        broker=get_settings().redis_url,
        broker_transport_options={"global_keyprefix": queue + ":"},
    )
    try:
        broker.send_task("app.discovery_tasks.discover_due", queue=queue, retry=False)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            assert process.poll() is None
            with Session(engine) as session:
                runs = session.scalars(select(JobFetch)).all()
                if len(runs) == MAX_BOARDS and all(run.status == "succeeded" for run in runs):
                    assert all(
                        run.query["automatic"] and run.worker.startswith("discovery-test@")
                        for run in runs
                    )
                    assert len(session.scalars(select(Job)).all()) == MAX_BOARDS
                    break
            time.sleep(0.2)
        else:
            pytest.fail("Isolated discovery worker did not persist all employer matches")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        broker.close()
        with redis.Redis.from_url(get_settings().redis_url) as connection:
            keys = list(connection.scan_iter(match=queue + ":*"))
            if keys:
                connection.delete(*keys)


def test_preference_update_preserves_schedule_and_legacy_clients_preserve_rules(discovery):
    engine, client, _ = discovery
    before = client.get("/api/discovery").json()
    rules = {
        "locations": ["US", "United States"],
        "include_unspecified_location": False,
        "leadership": "strict",
    }
    changed = client.put(
        "/api/discovery",
        json={
            "enabled": True,
            "boards": BOARDS,
            "match_preferences": rules,
        },
    )
    assert changed.status_code == 200
    assert changed.json()["next_run_at"] == before["next_run_at"]
    assert client.put("/api/discovery", json={"enabled": True, "boards": BOARDS}).json()[
        "match_preferences"
    ] == {**DEFAULT_RULES, **rules}
    with Session(engine) as session:
        assert not session.scalars(select(JobFetch)).all()
    for invalid in ({"leadership": "bad"}, {"locations": ["---"]}, {"unexpected": True}):
        assert client.put("/api/discovery", json={"match_preferences": invalid}).status_code == 422
    assert client.get("/api/discovery").json()["match_preferences"] == {**DEFAULT_RULES, **rules}


def test_saved_matches_refilter_without_deleting_rows_and_alerts_obey_rules(discovery, monkeypatch):
    from app.alert_tasks import evaluate_alerts
    from app.models import JobAlert

    engine, client, _ = discovery
    monkeypatch.setattr("app.alert_tasks.get_engine", lambda: engine)
    monkeypatch.setattr("app.alerts.check_alerts.apply_async", Mock())
    fixtures = [
        ("Engineering Manager", "US Remote"),
        ("Engineering Manager", "Remote Canada"),
        ("Technical Program Manager, Engineering", "US Remote"),
    ]
    for number, (title, location) in enumerate(fixtures):
        response = client.post(
            "/api/job-references",
            json={
                "title": title,
                "company": "Synthetic Employer",
                "location": location,
                "description": "Python test automation",
                "url": f"https://example.invalid/{number}",
            },
        )
        assert response.status_code == 201
    rules = {"locations": ["US"], "leadership": "strict"}
    assert (
        client.put(
            "/api/discovery", json={"boards": BOARDS, "match_preferences": rules}
        ).status_code
        == 200
    )
    result = client.get("/api/jobs?source=all&discovery_only=true&limit=1").json()
    assert result["total"] == result["summary"]["results"] == 1
    assert result["items"][0]["location"] == "US Remote"
    assert result["items"][0]["title"] == "Engineering Manager"
    assert client.get("/api/jobs?source=all").json()["total"] == 3
    saved = client.post(
        "/api/saved-searches",
        json={
            "name": "Synthetic matching",
            "source": "all",
            "filters": {"discovery_only": True},
        },
    ).json()
    assert client.get(f"/api/saved-searches/{saved['id']}").json()["filters"]["discovery_only"]
    assert (
        client.put(
            f"/api/saved-searches/{saved['id']}/alerts",
            json={
                "enabled": True,
                "min_score": 0,
            },
        ).status_code
        == 200
    )
    evaluate_alerts("worker@synthetic", UUID(saved["id"]))
    with Session(engine) as session:
        assert len(session.scalars(select(JobAlert)).all()) == 1
        assert len(session.scalars(select(Job)).all()) == 3
    assert (
        client.put(
            "/api/discovery",
            json={
                "boards": BOARDS,
                "match_preferences": {"leadership": "any"},
            },
        ).status_code
        == 200
    )
    assert client.get("/api/jobs?source=all&discovery_only=true").json()["total"] == 3


def test_worker_rechecks_location_preferences_changed_during_network_read(discovery, monkeypatch):
    engine, client, _ = discovery
    rows = enqueue_discovery(engine, publisher=Mock())

    def feed(*args):
        assert (
            client.put(
                "/api/discovery",
                json={
                    "boards": BOARDS,
                    "match_preferences": {"locations": ["US"]},
                },
            ).status_code
            == 200
        )
        return (
            [
                NormalizedJob(
                    external_id="foreign",
                    title="Director of Quality Engineering",
                    company="Example A",
                    location="Remote Canada",
                    description="Python test automation",
                    url="https://example.invalid/foreign",
                    posted_at=datetime.now(UTC),
                )
            ],
            1,
            0,
        )

    monkeypatch.setattr("app.sources.employer_boards.fetch_board", feed)
    execute_fetch(UUID(rows[0]["id"]), "worker@policy-change")
    with Session(engine) as session:
        run = session.get(JobFetch, UUID(rows[0]["id"]))
        assert run.status == "succeeded" and run.received_count == 1 and run.stored_count == 0
        assert not session.scalars(select(Job)).all()


def test_relevance_grouping_keeps_origins_and_filters_before_pagination(discovery):
    from app.job_identity import identity_key

    engine, client, _ = discovery
    with Session(engine) as session, session.begin():
        for source, external_id, company, location in (
            ("greenhouse", "one", "A", "US Remote"),
            ("lever", "two", "A", "US Remote"),
            ("greenhouse", "three", "B", "US Remote"),
            ("greenhouse", "four", "C", "Remote Canada"),
        ):
            title = "Director of Quality Engineering"
            session.add(
                Job(
                    source=source,
                    external_id=external_id,
                    company=company,
                    title=title,
                    location=location,
                    description="Python test automation",
                    url="https://example.invalid/job",
                    posted_at=datetime.now(UTC),
                    dedupe_key=identity_key(source, external_id, company, title, location),
                )
            )
    assert (
        client.put(
            "/api/discovery",
            json={
                "boards": BOARDS,
                "match_preferences": {"locations": ["US"]},
            },
        ).status_code
        == 200
    )
    pages = [
        client.get(f"/api/jobs?source=all&discovery_only=true&limit=1&offset={offset}").json()
        for offset in (0, 1)
    ]
    assert all(page["total"] == 2 and page["raw_total"] == 3 for page in pages)
    assert pages[0]["summary"] == pages[1]["summary"]
    grouped = next(page["items"][0] for page in pages if page["items"][0]["company"] == "A")
    assert {origin["source"] for origin in grouped["origins"]} == {"greenhouse", "lever"}
    assert (
        client.put("/api/profile", json={**PROFILE, "location": "Example City"}).status_code == 200
    )
    assert client.get("/api/jobs?source=all&discovery_only=true").status_code == 409
    assert client.get("/api/jobs?source=all").json()["raw_total"] == 4
