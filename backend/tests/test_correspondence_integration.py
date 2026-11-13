"""Correspondence sync against an isolated PostgreSQL schema with a mocked Gmail."""

# The public webmail and applicant-tracking domains in this file are intentional: mail
# detection keys on those exact domains, so a reserved example domain would not exercise
# it. Every local part, name and message body is synthetic.

import os
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from test_gmail import CONFIGURED, FakeGmail, message_payload
from test_google_calendar import FakeCalendar, event_payload
from test_profile_integration import profile_client as profile_client
from test_profile_integration import profile_database as profile_database

from app import application_intake
from app.correspondence_tasks import sync_calendar, sync_gmail
from app.followup_tasks import _evaluate_rules
from app.models import (
    CampaignTask,
    Communication,
    Contact,
    CorrespondenceSyncSettings,
    Pursuit,
    PursuitEvent,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1", reason="Requires PostgreSQL"
)


def test_sync_persists_review_queue_and_linking_records_reply(
    profile_client, profile_database, monkeypatch
):
    client, engine = profile_client, profile_database[0]
    monkeypatch.setattr("app.correspondence.get_settings", lambda: CONFIGURED)
    contact = client.post(
        "/api/contacts", json={"name": "Riley Recruiter", "email": "riley@acme.example"}
    ).json()
    assert (
        client.post(
            "/api/job-references",
            json={
                "title": "Director of Quality Engineering",
                "company": "Acme Example",
                "location": "US Remote",
                "description": "Synthetic posting for correspondence tests.",
                "url": "https://example.invalid/acme",
            },
        ).status_code
        == 201
    )
    with Session(engine) as session:
        session.execute(
            text(
                "INSERT INTO pursuits (id, job_key, job, stage, created_by) VALUES "
                "(gen_random_uuid(), 'acme-synthetic', "
                '\'{"company": "Acme Example", "title": "Director QE"}\', \'applied\', \'user\')'
            )
        )
        session.commit()
        pursuit_id = session.scalar(text("SELECT id FROM pursuits WHERE job_key='acme-synthetic'"))

    saved = client.put(
        "/api/correspondence",
        json={"enabled": True, "query": "label:synthetic", "max_messages_per_run": 10},
    )
    assert saved.status_code == 200 and saved.json()["enabled"] is True
    assert saved.json()["review_count"] == 0
    rules = {r["rule_key"]: r for r in client.get("/api/follow-up-rules").json()}
    assert rules["inbound_reply"]["enabled"] and rules["inbound_reply"]["delay_business_days"] == 3

    fake = FakeGmail(
        [
            message_payload(
                "g1",
                "Riley <riley@acme.example>",
                "Interview times",
                "Can you talk?",
                1_700_000_000_000,
            ),
            message_payload(
                "g2",
                "ats@greenhouse.io",
                "Acme Example application",
                "Received.",
                1_700_000_100_000,
            ),
        ]
    )
    with Session(engine) as session, session.begin():
        with fake.client() as http:
            first = sync_gmail(session, CONFIGURED, client=http)
        assert first == {
            "status": "ok",
            "imported": 2,
            "remaining": 0,
            "classifications": {"applied": 0, "suggested": 0, "disagreements": 0},
        }
    with Session(engine) as session, session.begin():
        with fake.client() as http:
            assert sync_gmail(session, CONFIGURED, client=http)["imported"] == 0, "idempotent"
    with Session(engine) as session:
        rows = session.scalars(select(Communication).order_by(Communication.received_at)).all()
        assert [r.source_id for r in rows] == ["g1", "g2"]
        assert rows[0].contact_id == UUID(contact["id"]) and rows[0].pursuit_id is None
        assert rows[0].suggested_pursuit_id == pursuit_id
        assert rows[1].contact_id is None and rows[1].suggested_pursuit_id == pursuit_id
        config = session.get(CorrespondenceSyncSettings, 1)
        assert config.last_status == "ok" and config.cursor_epoch == 1_700_000_100

    queue = client.get("/api/communications", params={"unlinked": "true"}).json()
    assert [c["source_id"] for c in queue] == ["g2"]
    assert queue[0]["suggested_company"] == "Acme Example"
    assert client.get("/api/correspondence").json()["review_count"] == 1

    # Mail that auto-linked to a contact skips the queue but still carries the suggestion,
    # so the contact timeline can offer the pursuit link later.
    riley = client.get("/api/communications", params={"contact_id": contact["id"]}).json()
    assert [c["source_id"] for c in riley] == ["g1"]
    assert riley[0]["suggested_company"] == "Acme Example" and riley[0]["pursuit_company"] is None

    # A queue item can take the contact and the pursuit in one update.
    linked = client.put(
        f"/api/communications/{queue[0]['id']}",
        json={"contact_id": contact["id"], "pursuit_id": str(pursuit_id)},
    )
    assert linked.status_code == 200
    assert linked.json()["contact_id"] == contact["id"]
    assert linked.json()["pursuit_id"] == str(pursuit_id)
    assert client.get("/api/communications", params={"unlinked": "true"}).json() == []
    with Session(engine) as session:
        events = session.scalars(select(PursuitEvent)).all()
        assert [e.message for e in events] == ["Received reply: Acme Example application"]
        assert (
            events[0].source == "gmail"
            and events[0].event_date == datetime.fromtimestamp(1_700_000_100, tz=UTC).date()
        )

    # The auto-linked contact mail gets its pursuit afterwards and records its own reply.
    later = client.put(
        f"/api/communications/{riley[0]['id']}", json={"pursuit_id": str(pursuit_id)}
    )
    assert later.status_code == 200 and later.json()["contact_id"] == contact["id"]
    riley = client.get("/api/communications", params={"contact_id": contact["id"]}).json()
    assert [c["pursuit_company"] for c in riley] == ["Acme Example", "Acme Example"]
    with Session(engine) as session:
        messages = session.scalars(
            select(PursuitEvent.message).order_by(PursuitEvent.created_at)
        ).all()
        assert messages == [
            "Received reply: Acme Example application",
            "Received reply: Interview times",
        ]

    # Changing the query resets the cursor so the new filter re-scans the initial window.
    changed = client.put(
        "/api/correspondence",
        json={"enabled": False, "query": "label:other", "max_messages_per_run": 10},
    ).json()
    assert changed["cursor_epoch"] is None and changed["enabled"] is False
    assert client.post("/api/correspondence/sync").status_code == 409


def test_dismissed_mail_leaves_the_queue_and_never_returns(
    profile_client, profile_database, monkeypatch
):
    client, engine = profile_client, profile_database[0]
    monkeypatch.setattr("app.correspondence.get_settings", lambda: CONFIGURED)
    assert (
        client.put(
            "/api/correspondence",
            json={"enabled": True, "query": "label:synthetic", "max_messages_per_run": 10},
        ).status_code
        == 200
    )
    contact = client.post(
        "/api/contacts", json={"name": "Front Desk", "email": "stay@hotel.example"}
    ).json()
    fake = FakeGmail(
        [
            message_payload(
                "h1", "stay@hotel.example", "Your stay is confirmed", "See you.", 1_700_000_000_000
            ),
            message_payload(
                "h2", "promo@hotel.example", "Weekend rates", "Book now.", 1_700_000_100_000
            ),
        ]
    )
    with Session(engine) as session, session.begin():
        with fake.client() as http:
            assert sync_gmail(session, CONFIGURED, client=http)["imported"] == 2
    queue = client.get("/api/communications", params={"unlinked": "true"}).json()
    assert [c["source_id"] for c in queue] == ["h2"]
    timeline = client.get("/api/communications", params={"contact_id": contact["id"]}).json()
    assert [c["source_id"] for c in timeline] == ["h1"]

    # Dismiss the queued promotion and the contact-linked confirmation alike.
    for row in (queue[0], timeline[0]):
        assert (
            client.put(
                f"/api/communications/{row['id']}",
                json={"status": "dismissed", "received_at": "2026-10-20T15:00:00Z"},
            ).status_code
            == 200
        )
    assert client.get("/api/communications", params={"unlinked": "true"}).json() == []
    assert client.get("/api/communications", params={"contact_id": contact["id"]}).json() == []
    assert client.get("/api/correspondence").json()["review_count"] == 0
    hidden = client.get("/api/communications", params={"status": "dismissed"}).json()
    assert sorted(c["source_id"] for c in hidden) == ["h1", "h2"]

    # A re-scan after a query change skips stored IDs, so dismissed mail never returns.
    assert (
        client.put(
            "/api/correspondence",
            json={"enabled": True, "query": "label:wider", "max_messages_per_run": 10},
        ).json()["cursor_epoch"]
        is None
    )
    with Session(engine) as session, session.begin():
        with fake.client() as http:
            assert sync_gmail(session, CONFIGURED, client=http)["imported"] == 0
    # Old, unanswered, linked to a contact, and still no follow-up task.
    with Session(engine) as session, session.begin():
        assert _evaluate_rules(session)["created"] == 0
    with Session(engine) as session:
        assert session.scalars(select(CampaignTask)).all() == []


def test_missed_reply_rule_creates_one_task_until_a_reply_is_logged(
    profile_client, profile_database, monkeypatch
):
    client, engine = profile_client, profile_database[0]
    monkeypatch.setattr("app.correspondence.get_settings", lambda: CONFIGURED)
    assert (
        client.put(
            "/api/correspondence",
            json={"enabled": True, "query": "label:synthetic", "max_messages_per_run": 10},
        ).status_code
        == 200
    )
    campaign = client.post(
        "/api/campaigns",
        json={
            "campaign_key": "synthetic",
            "title": "Synthetic",
            "start_date": "2026-11-01",
            "end_date": "2026-12-01",
        },
    ).json()
    contact = client.post("/api/contacts", json={"name": "Riley", "email": "r@acme.example"}).json()
    unlinked = client.post(
        "/api/communications",
        json={"direction": "inbound", "status": "received", "subject": "Unlinked"},
    ).json()
    old = client.post(
        "/api/communications",
        json={
            "contact_id": contact["id"],
            "direction": "inbound",
            "status": "received",
            "subject": "Are you available?",
            "body": "Hi Alex,\n\n" + "We would like to schedule a call. " * 40 + "\nBest,\nSam",
        },
    ).json()
    assert (
        client.put(
            f"/api/communications/{old['id']}", json={"received_at": "2026-10-20T15:00:00Z"}
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/api/communications/{unlinked['id']}", json={"received_at": "2026-10-20T15:00:00Z"}
        ).status_code
        == 200
    )

    def evaluate():
        with Session(engine) as session, session.begin():
            return _evaluate_rules(session)

    assert evaluate()["created"] == 1
    assert evaluate()["created"] == 0, "idempotent across runs"
    with Session(engine) as session:
        tasks = session.scalars(select(CampaignTask)).all()
        assert len(tasks) == 1
        assert tasks[0].seed_key == f"fu-{old['id'][:8]}-rpl"
        assert tasks[0].category == "follow_up" and tasks[0].priority == "P0"
        assert tasks[0].due_date == date(2026, 10, 23)
        assert tasks[0].title.startswith("Reply to ")
        assert str(tasks[0].communication_id) == old["id"]
    assert campaign["id"] == str(tasks[0].campaign_id)
    # The task carries the whole message so it can be acted on without opening Gmail.
    listed = client.get(f"/api/campaigns/{campaign['id']}/tasks").json()
    shown = next(t for t in listed if t["seed_key"] == f"fu-{old['id'][:8]}-rpl")
    assert shown["communication_id"] == old["id"]
    assert shown["communication"]["subject"] == "Are you available?"
    assert shown["communication"]["body"] == old["body"] and len(old["body"]) > 1000
    assert shown["communication"]["sender"] is None
    today_view = client.get("/api/today").json()
    everywhere = today_view["overdue_tasks"] + today_view["priority_actions"]
    assert any(t["communication"] and t["communication"]["body"] == old["body"] for t in everywhere)

    # A fresh inbound message that has been answered never produces a task.
    fresh = client.post(
        "/api/communications",
        json={
            "contact_id": contact["id"],
            "direction": "inbound",
            "status": "received",
            "subject": "Second note",
        },
    ).json()
    assert (
        client.put(
            f"/api/communications/{fresh['id']}", json={"received_at": "2026-10-21T15:00:00Z"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/communications",
            json={
                "contact_id": contact["id"],
                "direction": "outbound",
                "status": "sent",
                "subject": "Re: Second note",
            },
        ).status_code
        == 201
    )
    assert evaluate()["created"] == 0


def test_calendar_events_join_the_review_queue_and_link_like_mail(
    profile_client, profile_database, monkeypatch
):
    client, engine = profile_client, profile_database[0]
    settings = CONFIGURED.model_copy(update={"calendar_sync_enabled": True})
    monkeypatch.setattr("app.correspondence.get_settings", lambda: settings)
    contact = client.post(
        "/api/contacts", json={"name": "Riley", "email": "riley@acme.example"}
    ).json()
    saved = client.put(
        "/api/correspondence",
        json={
            "enabled": False,
            "query": "label:synthetic",
            "max_messages_per_run": 10,
            "calendar_enabled": True,
            "calendar_lookahead_days": 7,
        },
    )
    assert saved.status_code == 200 and saved.json()["calendar_enabled"] is True
    fake = FakeCalendar(
        [
            event_payload(
                "ev1",
                "Acme Example interview",
                "2026-11-06T15:00:00Z",
                [("riley@acme.example", "Riley")],
                hangoutLink="https://meet.example/y",
            ),
            event_payload("ev2", "Coffee with Sam", "2026-11-07T15:00:00Z"),
        ]
    )
    now = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
    for expected in (
        {"status": "ok", "imported": 2, "updated": 0},
        {"status": "ok", "imported": 0, "updated": 0},
    ):
        with Session(engine) as session, session.begin():
            with fake.client() as http:
                assert sync_calendar(session, settings, client=http, now=now) == expected
    with Session(engine) as session:
        rows = {r.source_id: r for r in session.scalars(select(Communication)).all()}
        assert rows["ev1"].contact_id == UUID(contact["id"])
        assert rows["ev1"].source == "calendar" and rows["ev1"].direction == "note"
        config = session.get(CorrespondenceSyncSettings, 1)
        # Status reflects the latest run, which found nothing new.
        assert config.calendar_last_status == "ok" and config.calendar_last_imported == 0
    queue = client.get("/api/communications", params={"unlinked": "true"}).json()
    assert [c["source_id"] for c in queue] == ["ev2"]
    assert client.get("/api/correspondence").json()["review_count"] == 1
    assert client.post("/api/correspondence/sync").status_code in (202, 503)


def test_thread_yields_one_task_and_a_logged_reply_joins_the_thread(
    profile_client, profile_database, monkeypatch
):
    client, engine = profile_client, profile_database[0]
    monkeypatch.setattr("app.correspondence.get_settings", lambda: CONFIGURED)
    assert client.put("/api/correspondence", json={"enabled": True}).status_code == 200
    campaign = client.post(
        "/api/campaigns",
        json={
            "campaign_key": "synthetic-thread",
            "title": "Synthetic",
            "start_date": "2026-11-01",
            "end_date": "2026-12-01",
        },
    ).json()
    contact = client.post("/api/contacts", json={"name": "Sam", "email": "s@acme.example"}).json()
    ids = []
    for day, subject in ((20, "First note"), (21, "Re: First note")):
        row = client.post(
            "/api/communications",
            json={
                "contact_id": contact["id"],
                "direction": "inbound",
                "status": "received",
                "subject": subject,
                "body": f"Message of day {day}",
                "thread_id": "thread-1",
            },
        ).json()
        assert row["thread_id"] == "thread-1"
        assert (
            client.put(
                f"/api/communications/{row['id']}",
                json={"received_at": f"2026-10-{day}T15:00:00Z"},
            ).status_code
            == 200
        )
        ids.append(row["id"])

    with Session(engine) as session, session.begin():
        assert _evaluate_rules(session)["created"] == 1, "one task per thread, not per mail"
    with Session(engine) as session:
        task = session.scalar(
            select(CampaignTask).where(CampaignTask.campaign_id == UUID(campaign["id"]))
        )
        assert str(task.communication_id) == ids[1], "the newest message in the thread"

    # The reply drafted from the task keeps the thread and names the task; once sent,
    # nothing in the thread is due any more.
    reply = client.post(
        "/api/communications",
        json={
            "contact_id": contact["id"],
            "campaign_task_id": str(task.id),
            "direction": "outbound",
            "status": "sent",
            "subject": "Re: First note",
            "body": "Thanks Sam, Friday works.",
            "thread_id": "thread-1",
        },
    )
    assert reply.status_code == 201 and reply.json()["thread_id"] == "thread-1"
    listed = client.get(f"/api/communications?contact_id={contact['id']}").json()
    assert sorted(m["thread_id"] for m in listed) == ["thread-1"] * 3
    with Session(engine) as session, session.begin():
        assert _evaluate_rules(session)["created"] == 0


def test_confirmation_email_creates_application_contact_and_tracking_and_can_be_undone(
    profile_client, profile_database, monkeypatch
):
    client, engine = profile_client, profile_database[0]
    monkeypatch.setattr("app.correspondence.get_settings", lambda: CONFIGURED)
    saved = client.put(
        "/api/correspondence",
        json={
            "enabled": True,
            "query": "label:synthetic",
            "max_messages_per_run": 10,
            "auto_create_applications": True,
        },
    )
    assert saved.status_code == 200 and saved.json()["auto_create_applications"] is True
    rules = {r["rule_key"]: r for r in client.get("/api/follow-up-rules").json()}
    assert rules["application_review"]["delay_business_days"] == 5
    client.post(
        "/api/campaigns",
        json={
            "campaign_key": "synthetic",
            "title": "Synthetic",
            "start_date": "2026-11-01",
            "end_date": "2026-12-01",
        },
    )
    riley = client.post(
        "/api/contacts", json={"name": "Riley", "email": "riley@globex.example"}
    ).json()
    with Session(engine) as session:
        session.execute(
            text(
                "INSERT INTO pursuits (id, job_key, job, stage, created_by) VALUES "
                "(gen_random_uuid(), 'globex-synthetic', "
                '\'{"company": "Globex", "title": "Platform Engineer"}\', \'review\', \'manual\')'
            )
        )
        session.commit()
        globex_id = session.scalar(text("SELECT id FROM pursuits WHERE job_key='globex-synthetic'"))

    received = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)
    epoch = int(received.timestamp() * 1000)
    fake = FakeGmail(
        [
            message_payload(
                "c1",
                # Some mailers repeat the address as the display name.
                '"no-reply@acme.example" <no-reply@acme.example>',
                "Thank You for Applying to Acme - 10001 - Director, Quality Engineering",
                "We have received your application.",
                epoch,
            ),
            message_payload(
                "c2",
                "Riley <riley@globex.example>",
                "Thank you for applying to Globex - Platform Engineer",
                "Thanks, we received your application.",
                epoch + 1000,
            ),
            message_payload(
                "c3", "no-reply@initech.example", "Application received", "Thanks!", epoch + 2000
            ),
            message_payload(
                "away",
                "Riley <riley@globex.example>",
                "Automatic reply: Platform Engineer",
                "Out of office.",
                epoch + 3000,
            ),
        ]
    )
    with Session(engine) as session, session.begin():
        with fake.client() as http:
            assert sync_gmail(session, CONFIGURED, client=http)["imported"] == 4
        session.flush()
        assert application_intake.run(session) == {
            "status": "ok",
            "created": 1,
            "advanced": 1,
            "linked": 0,
        }
    with Session(engine) as session, session.begin():
        assert application_intake.run(session)["created"] == 0, "idempotent"

    with Session(engine) as session:
        rows = {r.source_id: r for r in session.scalars(select(Communication)).all()}
        acme = session.get(Pursuit, rows["c1"].pursuit_id)
        assert acme.stage == "applied" and acme.applied_at == received
        assert acme.created_by == "email" and acme.next_action_on == date(2026, 10, 27)
        assert acme.job["company"] == "Acme" and acme.job["requisition"] == "10001"
        assert acme.job["title"] == "Director, Quality Engineering"
        acme_id = acme.id
        mailbox = session.get(Contact, rows["c1"].contact_id)
        assert mailbox.email == "no-reply@acme.example" and mailbox.do_not_contact
        assert mailbox.name == "Acme Talent Acquisition" and mailbox.company == "Acme"
        mailbox_id = mailbox.id
        globex = session.get(Pursuit, globex_id)
        assert rows["c2"].pursuit_id == globex_id and globex.stage == "applied"
        assert globex.applied_at == received.replace(second=1) and globex.version == 2
        assert rows["c2"].contact_id == UUID(riley["id"]), "an existing contact is reused"
        assert rows["c3"].pursuit_id is None and rows["c3"].detection["confidence"] == "medium"
        events = session.scalars(select(PursuitEvent.message)).all()
        assert "Application detected from confirmation email" in events
        assert "Confirmation email recorded stage: review → applied" in events
        assert not [e for e in events if "reply" in e.lower()], "a confirmation is not a reply"

    tracked = {p["id"]: p for p in client.get("/api/career").json()["items"]}
    assert tracked[str(acme_id)]["stage"] == "applied"
    queue = client.get("/api/communications", params={"unlinked": "true"}).json()
    assert [c["source_id"] for c in queue] == ["c3"]

    with Session(engine) as session, session.begin():
        _evaluate_rules(session)
    with Session(engine) as session:
        titles = sorted(session.scalars(select(CampaignTask.title)).all())
        assert titles == [
            "Review application status: Director, Quality Engineering at Acme",
            "Review application status: Platform Engineer at Globex",
        ], "status checks are raised; confirmations and automatic replies need no answer"

    # A medium-confidence detection waits for the user, who supplies the missing role.
    c3 = queue[0]["id"]
    assert client.post(f"/api/communications/{c3}/application", json={}).status_code == 422
    made = client.post(f"/api/communications/{c3}/application", json={"title": "Staff Engineer"})
    assert made.status_code == 201 and made.json()["created"] is True
    assert made.json()["company"] == "Initech" and made.json()["stage"] == "applied"
    assert client.post(f"/api/communications/{c3}/application", json={}).status_code == 409

    # Undo removes what the message created and keeps the next sync from recreating it.
    c1 = next(
        c["id"]
        for c in client.get("/api/communications", params={"pursuit_id": str(acme_id)}).json()
    )
    assert client.delete(f"/api/communications/{c1}/application").status_code == 204
    assert client.delete(f"/api/communications/{c1}/application").status_code == 409
    with Session(engine) as session, session.begin():
        assert session.get(Pursuit, acme_id) is None
        assert session.get(Contact, mailbox_id) is None
        assert application_intake.run(session)["created"] == 0
        row = session.scalar(select(Communication).where(Communication.source_id == "c1"))
        assert row.pursuit_id is None and row.contact_id is None
        assert row.detection["undone"] is True and "applied" not in row.detection
        assert session.scalars(select(CampaignTask.title)).all() == [
            "Review application status: Platform Engineer at Globex"
        ]

    # Undoing an advanced application restores its earlier stage and keeps the contact.
    c2 = next(
        c["id"]
        for c in client.get("/api/communications", params={"pursuit_id": str(globex_id)}).json()
        if c["source_id"] == "c2"
    )
    assert client.delete(f"/api/communications/{c2}/application").status_code == 204
    with Session(engine) as session:
        globex = session.get(Pursuit, globex_id)
        assert globex.stage == "review" and globex.applied_at is None
        assert session.get(Contact, UUID(riley["id"])) is not None
        assert session.scalars(select(CampaignTask.title)).all() == []


def test_listing_pages_newest_first_and_recorded_contact_stops_the_status_check(
    profile_client, profile_database
):
    client, engine = profile_client, profile_database[0]
    for number in range(5):
        created = client.post(
            "/api/communications",
            json={"direction": "inbound", "status": "received", "subject": f"m{number}"},
        ).json()
        client.put(
            f"/api/communications/{created['id']}",
            json={"received_at": f"2026-10-{10 + number:02d}T12:00:00Z"},
        )

    def page(**params):
        return [c["subject"] for c in client.get("/api/communications", params=params).json()]

    assert page() == ["m4", "m3", "m2", "m1", "m0"], "ordered by when the mail arrived"
    assert page(limit=2) == ["m4", "m3"] and page(limit=2, offset=2) == ["m2", "m1"]
    assert page(limit=2, offset=4) == ["m0"]
    assert client.get("/api/communications", params={"limit": 201}).status_code == 422

    client.post(
        "/api/campaigns",
        json={
            "campaign_key": "synthetic",
            "title": "Synthetic",
            "start_date": "2026-11-01",
            "end_date": "2026-12-01",
        },
    )
    client.post(
        "/api/follow-up-rules",
        json={
            "rule_key": "application_review",
            "trigger": "application_without_response",
            "delay_business_days": 5,
        },
    )
    with Session(engine) as session:
        for key, company in (("quiet", "Acme"), ("contacted", "Globex")):
            session.execute(
                text(
                    "INSERT INTO pursuits (id, job_key, job, stage, created_by, applied_at)"
                    " VALUES (gen_random_uuid(), :key, :job, 'applied', 'manual',"
                    " '2026-10-01T12:00:00Z')"
                ),
                {"key": key, "job": f'{{"company": "{company}", "title": "Director QE"}}'},
            )
        session.commit()
        contacted = session.scalar(text("SELECT id FROM pursuits WHERE job_key='contacted'"))
    recorded = client.post(
        f"/api/career/pursuits/{contacted}/contact",
        json={"version": 1, "note": "Emailed the recruiter for an update"},
    )
    assert recorded.status_code == 200
    with Session(engine) as session, session.begin():
        _evaluate_rules(session)
    with Session(engine) as session:
        assert session.scalars(select(CampaignTask.title)).all() == [
            "Review application status: Director QE at Acme"
        ], "contact you recorded after applying makes the status check redundant"


def test_stage_suggestions_are_confirmed_or_ignored_and_recruiter_mail_starts_an_application(
    profile_client, profile_database, monkeypatch
):
    client, engine = profile_client, profile_database[0]
    monkeypatch.setattr("app.correspondence.get_settings", lambda: CONFIGURED)
    client.put(
        "/api/correspondence",
        json={"enabled": True, "query": "label:synthetic", "max_messages_per_run": 10},
    )
    client.post(
        "/api/campaigns",
        json={
            "campaign_key": "synthetic",
            "title": "Synthetic",
            "start_date": "2026-11-01",
            "end_date": "2026-12-01",
        },
    )
    with Session(engine) as session:
        for key, company in (("acme", "Acme"), ("globex", "Globex")):
            session.execute(
                text(
                    "INSERT INTO pursuits (id, job_key, job, stage, created_by, applied_at)"
                    " VALUES (gen_random_uuid(), :key, :job, 'applied', 'manual', now())"
                ),
                {"key": key, "job": f'{{"company": "{company}", "title": "Director QE"}}'},
            )
        session.commit()
        acme_id = session.scalar(text("SELECT id FROM pursuits WHERE job_key='acme'"))
        globex_id = session.scalar(text("SELECT id FROM pursuits WHERE job_key='globex'"))

    epoch = 1_700_000_000_000
    recruiter = [
        message_payload(
            f"k{n}",
            "Riley Recruiter <riley@staffco.example>",
            "Sam [Initech] - Resume (2026)",
            "My client Initech is hiring a director.",
            epoch + n,
        )
        for n in (1, 2)
    ]
    for payload in recruiter:
        payload["threadId"] = "t-recruiter"
    fake = FakeGmail(
        [
            message_payload(
                "rej",
                "Globex Careers <no-reply@globex.example>",
                "Update on your application to Globex",
                "Thank you for applying. Unfortunately we are moving forward with other"
                " candidates.",
                epoch + 10,
            ),
            message_payload(
                "inv",
                "Riley <riley@acme.example>",
                "Availability for a phone interview",
                "Are you free Tuesday?",
                epoch + 20,
            ),
            *recruiter,
        ]
    )
    with Session(engine) as session, session.begin():
        with fake.client() as http:
            assert sync_gmail(session, CONFIGURED, client=http)["imported"] == 4

    suggestions = {s["stage"]: s for s in client.get("/api/stage-suggestions").json()}
    assert set(suggestions) == {"rejected", "interview"}
    assert suggestions["rejected"]["pursuit_id"] == str(globex_id)
    assert suggestions["rejected"]["current_stage"] == "applied"
    assert suggestions["interview"]["company"] == "Acme"
    assert suggestions["interview"]["communication"]["body"] == "Are you free Tuesday?"

    invite = suggestions["interview"]["communication"]["id"]
    confirmed = client.post(
        f"/api/communications/{invite}/stage-suggestion", json={"decision": "apply"}
    )
    assert confirmed.status_code == 200 and confirmed.json()["current_stage"] == "interview"
    decline = suggestions["rejected"]["communication"]["id"]
    ignored = client.post(
        f"/api/communications/{decline}/stage-suggestion", json={"decision": "ignore"}
    )
    assert ignored.status_code == 200 and ignored.json()["current_stage"] == "applied"
    assert client.get("/api/stage-suggestions").json() == []
    again = client.post(
        f"/api/communications/{decline}/stage-suggestion", json={"decision": "apply"}
    )
    assert again.status_code == 409
    with Session(engine) as session:
        acme = session.get(Pursuit, acme_id)
        assert acme.stage == "interview" and acme.version == 2
        assert session.get(Pursuit, globex_id).stage == "applied"
        linked = session.scalar(select(Communication).where(Communication.source_id == "inv"))
        assert linked.pursuit_id == acme_id
        assert linked.detection["stage_decision"]["previous_stage"] == "applied"
        task = session.scalar(select(CampaignTask))
        assert task.title == "Prepare for interview: Director QE at Acme"
        assert task.category == "interview" and task.communication_id == linked.id
        assert (
            "Email recorded stage: applied → interview"
            in session.scalars(select(PursuitEvent.message)).all()
        )
    with Session(engine) as session, session.begin():
        _evaluate_rules(session)
    with Session(engine) as session:
        titles = session.scalars(select(CampaignTask.title)).all()
        assert not [t for t in titles if t.startswith("Reply to Globex")], "no answer is owed"

    # A recruiter's first message starts an application before anything was submitted.
    queue = client.get("/api/communications", params={"unlinked": "true"}).json()
    first = next(c for c in queue if c["source_id"] == "k1")
    assert first["detection"]["kind"] == "none"
    made = client.post(
        f"/api/communications/{first['id']}/application",
        json={"company": "Initech", "title": "Director QE", "stage": "preparing"},
    )
    assert made.status_code == 201 and made.json()["stage"] == "preparing"
    initech_id = UUID(made.json()["pursuit_id"])
    with Session(engine) as session:
        initech = session.get(Pursuit, initech_id)
        assert initech.applied_at is None and initech.created_by == "email"
        thread = session.scalars(
            select(Communication).where(Communication.thread_id == "t-recruiter")
        ).all()
        assert {m.pursuit_id for m in thread} == {initech_id}, "the whole thread is linked"
        riley = session.get(Contact, UUID(made.json()["contact_id"]))
        assert riley.name == "Riley Recruiter" and not riley.do_not_contact
        assert riley.company == "Staffco" and riley.relationship == "recruiter"
        assert "Recruiting for Initech" in riley.notes
        rules = session.scalars(text("SELECT rule_key FROM follow_up_rules")).all()
        assert "application_review" not in rules, "nothing was applied for yet"
    assert not [
        c
        for c in client.get("/api/communications", params={"unlinked": "true"}).json()
        if c["thread_id"] == "t-recruiter"
    ]
    assert client.delete(f"/api/communications/{first['id']}/application").status_code == 204
    with Session(engine) as session:
        assert session.get(Pursuit, initech_id) is None
        thread = session.scalars(
            select(Communication).where(Communication.thread_id == "t-recruiter")
        ).all()
        assert {m.pursuit_id for m in thread} == {None}
