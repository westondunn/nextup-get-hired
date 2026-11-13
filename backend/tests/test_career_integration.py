"""Career workflow on synthetic schemas; no applications/messages are delivered."""

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import integration_db
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from test_profile_integration import profile_client as profile_client
from test_profile_integration import profile_database as profile_database

from app.career import reconcile_plan
from app.models import Campaign, CareerSettings, Job, Pursuit, PursuitEvent

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1", reason="Requires PostgreSQL"
)
PROFILE = {
    "skills": ["Python", "Test automation"],
    "target_titles": ["Director of Quality Engineering"],
    "location": "Synthetic City",
    "work_preferences": ["remote"],
}


@pytest.fixture
def career(profile_client, profile_database):
    client, engine = profile_client, profile_database[0]
    assert client.put("/api/profile", json=PROFILE).status_code == 200
    assert (
        client.put(
            "/api/discovery",
            json={
                "enabled": False,
                "boards": [],
                "match_preferences": {"locations": ["US"], "leadership": "strict"},
            },
        ).status_code
        == 200
    )
    for n in range(8):
        assert (
            client.post(
                "/api/job-references",
                json={
                    "title": "Director of Quality Engineering",
                    "company": f"Synthetic {n}",
                    "location": "US Remote",
                    "description": (
                        "Python test automation. A job description is not an achievement."
                    ),
                    "url": f"https://example.invalid/{n}",
                },
            ).status_code
            == 201
        )
    assert (
        client.put(
            "/api/career/preferences",
            json={
                "automatic": True,
                "daily_limit": 3,
                "timezone": "America/New_York",
                "minimum_annual_usd": 100000,
            },
        ).status_code
        == 200
    )
    return client, engine


def update_body(item, **changes):
    return {
        key: changes.get(key, item[key])
        for key in (
            "version",
            "stage",
            "notes",
            "application_draft",
            "outreach_draft",
            "next_action_on",
        )
    }


def test_planner_backlog_daily_limit_idempotence_and_truthful_drafts(career):
    client, engine = career
    now = datetime.now(UTC)
    with Session(engine) as session, session.begin():
        assert reconcile_plan(session, "synthetic-worker", now=now)["added"] == 3
    with Session(engine) as session, session.begin():
        assert reconcile_plan(session, "retry", now=now)["added"] == 0
    data = client.get("/api/career").json()
    assert len(data["items"]) == len(data["plan"]) == 3
    assert data["counts"]["applied"] == 0 and data["delivery"] == "local_drafts_only"
    first = data["items"][0]
    assert "Relevant skills: Python, Test automation" in first["application_draft"]
    assert "[Add a verified achievement" in first["application_draft"]
    assert "A job description is not an achievement" not in first["application_draft"]
    assert any("100,000" in check for check in first["checks"])
    assert len(client.get(f"/api/career/pursuits/{first['id']}/events").json()) == 1
    assert (
        client.put(
            f"/api/career/pursuits/{first['id']}", json=update_body(first, stage="dismissed")
        ).status_code
        == 200
    )
    with Session(engine) as session, session.begin():
        assert reconcile_plan(session, "same-day", now=now)["added"] == 0
    with Session(engine) as session, session.begin():
        assert reconcile_plan(session, "next-day", now=now + timedelta(days=1))["added"] == 1
    with Session(engine) as session:
        assert session.get(Pursuit, UUID(first["id"])).stage == "dismissed"
        assert session.scalar(
            select(PursuitEvent.id).where(PursuitEvent.pursuit_id == UUID(first["id"]))
        )
    assert client.get("/api/profile").json() == PROFILE


def test_manual_tracking_deduplicates_and_worker_never_overwrites_progress(career):
    client, engine = career
    job = client.get("/api/jobs?source=all").json()["items"][0]
    payload = {"source": job["source"], "external_id": job["external_id"]}
    first = client.post("/api/career/pursuits", json=payload).json()
    assert first["created"] is True
    assert client.post("/api/career/pursuits", json=payload).json() == {
        "id": first["id"],
        "created": False,
    }
    item = client.get("/api/career").json()["items"][0]
    changed = client.put(
        f"/api/career/pursuits/{item['id']}",
        json=update_body(
            item,
            stage="preparing",
            notes="Contact after resume review",
            application_draft="My own carefully edited draft",
        ),
    ).json()
    with Session(engine) as session, session.begin():
        assert reconcile_plan(session, "synthetic")["added"] == 2
    same = next(p for p in client.get("/api/career").json()["items"] if p["id"] == item["id"])
    assert same["application_draft"] == changed["application_draft"]
    assert same["notes"] == changed["notes"] and same["version"] == changed["version"]
    # A duplicate source record shares the same pipeline entry.
    with Session(engine) as session, session.begin():
        original = session.get(Job, (job["source"], job["external_id"]))
        columns = {c.name: getattr(original, c.name) for c in Job.__table__.columns}
        columns.update(source="greenhouse", external_id="synthetic:duplicate")
        session.add(Job(**columns))
    duplicate = client.post(
        "/api/career/pursuits", json={"source": "greenhouse", "external_id": "synthetic:duplicate"}
    ).json()
    assert duplicate == {"id": first["id"], "created": False}


def test_applied_followup_history_conflicts_and_closed_actions(career):
    client, _ = career
    assert client.post("/api/career/plan").json()["added"] == 3
    item = client.get("/api/career").json()["items"][0]
    path = f"/api/career/pursuits/{item['id']}"
    applied = client.put(path, json=update_body(item, stage="applied", next_action_on=None)).json()
    assert applied["applied_at"] and not applied["due"]
    assert applied["next_action_on"] > client.get("/api/career").json()["today"]
    assert "following up on my application" in applied["follow_up_draft"]
    assert client.put(path, json=update_body(item, notes="stale overwrite")).status_code == 409
    assert (
        client.post(
            path + "/contact", json={"version": item["version"], "note": "stale event"}
        ).status_code
        == 409
    )
    result = client.post(
        path + "/contact", json={"version": applied["version"], "note": "Sent a follow-up manually"}
    )
    assert result.status_code == 200 and result.json()["stage"] == "applied"
    events = client.get(path + "/events").json()
    assert len(events) == 3 and any("You recorded contact" in e["message"] for e in events)
    archived = client.put(path, json=update_body(result.json(), stage="rejected")).json()
    assert archived["next_action_on"] is None
    assert (
        client.post(
            path + "/contact", json={"version": archived["version"], "note": "No send"}
        ).status_code
        == 409
    )
    assert client.put(path, json=update_body(archived, stage="emailed")).status_code == 422


def test_automatic_pause_profile_gate_and_locked_settings(career):
    client, engine = career
    assert client.put("/api/career/preferences", json={"automatic": False}).status_code == 200
    with Session(engine) as session, session.begin():
        assert reconcile_plan(session, "paused")["status"] == "paused"
    assert client.get("/api/career").json()["total"] == 0
    with Session(engine) as locker, locker.begin():
        locker.get(CareerSettings, 1, with_for_update=True)
        with Session(engine) as session, session.begin():
            assert reconcile_plan(session, "overlap")["added"] == 0
    client.put("/api/profile", json={**PROFILE, "location": "Example City"})
    assert client.post("/api/career/plan").json()["status"] == "profile_required"
    assert client.get("/api/career").json()["total"] == 0


def test_validation_and_get_never_create_records(profile_client, profile_database):
    client, engine = profile_client, profile_database[0]
    assert client.get("/api/career").status_code == 200
    with Session(engine) as session:
        assert session.get(CareerSettings, 1) is None
    for value in (
        {"timezone": "Missing/Place"},
        {"minimum_annual_usd": -1},
        {"daily_limit": True},
        {"start_by": "2026-02-30"},
        {"send_automatically": True},
    ):
        assert client.put("/api/career/preferences", json=value).status_code == 422
    assert client.post("/api/career/plan").json()["status"] == "not_configured"
    assert (
        client.post(
            "/api/career/pursuits", json={"source": "reference", "external_id": "missing"}
        ).status_code
        == 404
    )


def test_timezone_day_boundary_uses_local_calendar(career):
    client, engine = career
    # Both instants share a UTC date, but lie on different New York calendar days
    # (UTC-5: daylight saving ended on 2026-11-01). The zone is a generic IANA example.
    before = datetime(2026, 11, 2, 4, 59, tzinfo=UTC)
    after = before + timedelta(minutes=2)
    with Session(engine) as session, session.begin():
        assert reconcile_plan(session, "first", now=before)["added"] == 3
    with Session(engine) as session, session.begin():
        for row in session.scalars(select(Pursuit)):
            row.stage = "dismissed"
        assert reconcile_plan(session, "next-local-day", now=after)["added"] == 3


CAMPAIGN_DATES = {"start_date": "2026-11-01", "end_date": "2026-12-01"}
TIMEZONE_COLUMN_DEFAULT = """
    SELECT pg_get_expr(d.adbin, d.adrelid)
    FROM pg_attrdef d
    JOIN pg_attribute a ON a.attrelid = d.adrelid AND a.attnum = d.adnum
    JOIN pg_class c ON c.oid = d.adrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = :schema AND c.relname = 'campaigns' AND a.attname = 'timezone'
"""


def test_campaign_created_without_a_timezone_is_utc_in_the_api_and_the_database(
    profile_client, profile_database
):
    client, (engine, schema) = profile_client, profile_database
    created = client.post(
        "/api/campaigns",
        json={"campaign_key": "synthetic-default-zone", "title": "Synthetic", **CAMPAIGN_DATES},
    )
    assert created.status_code == 201
    campaign = created.json()
    assert campaign["timezone"] == "UTC"
    assert client.get(f"/api/campaigns/{campaign['id']}").json()["timezone"] == "UTC"
    assert [c["timezone"] for c in client.get("/api/campaigns").json()] == ["UTC"]
    assert Campaign.__table__.c.timezone.default.arg == "UTC", "the application's own default"
    with Session(engine) as session:
        stored = session.scalar(
            select(Campaign.timezone).where(Campaign.campaign_key == "synthetic-default-zone")
        )
        assert stored == "UTC"
        # The application writes the zone explicitly. The column also has a database
        # default, set by a pinned migration, and that default is a different value; so
        # the stored UTC cannot have come from it. If a later revision changes the column
        # default to UTC, replace the last assertion below.
        column_default = session.scalar(text(TIMEZONE_COLUMN_DEFAULT), {"schema": schema})
        assert column_default
        assert "UTC" not in column_default


def test_campaign_keeps_an_explicitly_supplied_timezone(profile_client, profile_database):
    client, engine = profile_client, profile_database[0]
    created = client.post(
        "/api/campaigns",
        json={
            "campaign_key": "synthetic-explicit-zone",
            "title": "Synthetic",
            "timezone": "Europe/Berlin",
            **CAMPAIGN_DATES,
        },
    )
    assert created.status_code == 201
    campaign = created.json()
    assert campaign["timezone"] == "Europe/Berlin"
    assert client.get(f"/api/campaigns/{campaign['id']}").json()["timezone"] == "Europe/Berlin"
    with Session(engine) as session:
        stored = session.scalar(
            select(Campaign.timezone).where(Campaign.campaign_key == "synthetic-explicit-zone")
        )
        assert stored == "Europe/Berlin"
    changed = client.put(f"/api/campaigns/{campaign['id']}", json={"timezone": "UTC"})
    assert changed.status_code == 200
    assert changed.json()["timezone"] == "UTC"


def test_real_broker_worker_prepares_local_plan(career, profile_database):
    import subprocess
    import sys
    import time

    import redis
    from celery import Celery

    from app.config import get_settings

    _, engine = career
    queue = "nextup_career_test_" + uuid4().hex
    code = (
        integration_db.SUBPROCESS_ENGINE
        + """
from app.celery_app import celery_app
celery_app.conf.broker_transport_options={**celery_app.conf.broker_transport_options,'global_keyprefix':os.environ['NEXTUP_TEST_QUEUE']+':'}
celery_app.worker_main(['worker','--pool=solo','--loglevel=ERROR','--without-gossip','--without-mingle','--without-heartbeat','-Q',os.environ['NEXTUP_TEST_QUEUE'],'--hostname=career-test@%h'])
"""
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        env=integration_db.schema_runtime_environment(profile_database[1], NEXTUP_TEST_QUEUE=queue),
    )
    broker = Celery(
        "career-test",
        broker=get_settings().redis_url,
        broker_transport_options={"global_keyprefix": queue + ":"},
    )
    try:
        broker.send_task("app.career_tasks.prepare_plan", queue=queue, retry=False)
        broker.send_task("app.career_tasks.prepare_plan", queue=queue, retry=False)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            assert process.poll() is None
            with Session(engine) as session:
                settings = session.get(CareerSettings, 1)
                if settings.worker and settings.worker.startswith("career-test@"):
                    assert len(session.scalars(select(Pursuit)).all()) == 3
                    assert len(session.scalars(select(PursuitEvent)).all()) == 3
                    break
            time.sleep(0.2)
        else:
            pytest.fail("Worker did not prepare and persist the plan")
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
