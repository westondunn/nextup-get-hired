# ruff: noqa: E501 -- the classifier contract SQL below is kept verbatim
"""Classifications written by the external classifier's exact SQL, applied by the Gmail sync."""

# The public webmail and applicant-tracking domains in this file are intentional: mail
# detection keys on those exact domains, so a reserved example domain would not exercise
# it. Every local part, name and message body is synthetic.

import os
from uuid import UUID

import pytest
from psycopg import sql
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from test_gmail import CONFIGURED, FakeGmail, message_payload
from test_profile_integration import profile_client as profile_client
from test_profile_integration import profile_database as profile_database

from app import application_intake
from app.correspondence_tasks import sync_gmail
from app.email_classifications import HINT_KEY
from app.models import Communication, EmailClassification

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1", reason="Requires PostgreSQL"
)

# Verbatim from the external email-labeler contract; do not edit.
CONTRACT = """
  INSERT INTO email_classifications
    (gmail_message_id, thread_id, classification, companies, company_id, confidence, model, prompt_version)
  VALUES ($1, $2, $3, string_to_array(NULLIF($4, ''), '|'), NULLIF($5, '')::uuid, $6::numeric, $7, $8)
  ON CONFLICT (gmail_message_id) DO UPDATE SET
    thread_id = EXCLUDED.thread_id, classification = EXCLUDED.classification,
    companies = EXCLUDED.companies, company_id = EXCLUDED.company_id,
    confidence = EXCLUDED.confidence, model = EXCLUDED.model,
    prompt_version = EXCLUDED.prompt_version, classified_at = now(), applied_at = NULL;
"""


def classify(engine, *params):
    """Run the contract as the classifier does: one prepared statement, eight string parameters."""
    with Session(engine) as session:
        raw = session.connection().connection.driver_connection
        raw.execute(f"PREPARE classify_message AS {CONTRACT}")
        raw.execute(
            sql.SQL("EXECUTE classify_message ({})").format(
                sql.SQL(", ").join(sql.Literal(p) for p in params)
            )
        )
        raw.execute("DEALLOCATE classify_message")  # pooled connections are reused
        session.commit()


def sync(engine, fake):
    with Session(engine) as session, session.begin():
        with fake.client() as http:
            result = sync_gmail(session, CONFIGURED, client=http)
        session.flush()
        application_intake.run(session)
        return result


def stored(engine, message_id):
    with Session(engine) as session:
        row = session.scalar(select(Communication).where(Communication.source_id == message_id))
        hint = session.get(EmailClassification, message_id)
        return row, hint


def track(client, company, title):
    reference = client.post(
        "/api/job-references",
        json={
            "title": title,
            "company": company,
            "location": "US Remote",
            "description": "Synthetic posting.",
            "url": f"https://example.invalid/{company}/{title}".replace(" ", "-"),
        },
    ).json()
    pursuit_id = client.post("/api/career/pursuits", json=reference).json()["id"]
    return next(i for i in client.get("/api/career").json()["items"] if i["id"] == pursuit_id)


@pytest.fixture
def mailbox(profile_client, profile_database, monkeypatch):
    client, engine = profile_client, profile_database[0]
    monkeypatch.setattr("app.correspondence.get_settings", lambda: CONFIGURED)
    saved = client.put(
        "/api/correspondence",
        json={
            "enabled": True,
            "query": "label:synthetic",
            "max_messages_per_run": 20,
            "auto_create_applications": True,
        },
    )
    assert saved.status_code == 200
    return client, engine


EPOCH = 1_700_000_000_000


def outreach(message_id, offset=0):
    """Recruiter mail that names no employer, so Nextup suggests nothing on its own."""
    return message_payload(
        message_id,
        "Riley <riley@gmail.com>",
        "Quick question",
        "Do you have time to talk this week about a director role?",
        EPOCH + offset,
    )


def test_classification_written_before_import_is_applied_in_the_same_run(mailbox):
    client, engine = mailbox
    open_job = track(client, "Acme Robotics", "Director of Quality")
    classify(
        engine,
        "m1",
        "t-m1",
        "opportunity",
        "Acme Robotics|Acme",
        open_job["company_id"],
        "0.912",
        "example-model",
        "p1",
    )
    result = sync(engine, FakeGmail([outreach("m1")]))
    assert result["imported"] == 1
    assert result["classifications"] == {"applied": 1, "suggested": 1, "disagreements": 0}

    row, hint = stored(engine, "m1")
    assert row.detection["kind"] == "none" and row.detection["v"] == 2, "Nextup keys kept"
    verdict = row.detection[HINT_KEY]
    assert verdict["classification"] == "opportunity"
    assert verdict["companies"] == ["Acme Robotics", "Acme"]
    assert verdict["company_id"] == open_job["company_id"]
    assert verdict["company_name"] == "Acme Robotics"
    assert verdict["confidence"] == 0.912 and verdict["model"] == "example-model"
    assert verdict["prompt_version"] == "p1" and verdict["agrees"] is None
    assert row.suggested_pursuit_id == UUID(open_job["id"]), "company -> open pursuit"
    assert row.pursuit_id is None and row.status == "received", "only a suggestion"
    assert hint.applied_at is not None

    # Listing exposes the matched company and filters by the hint.
    listed = client.get("/api/communications", params={"classifier_classification": "opportunity"})
    assert [(c["source_id"], c["classifier_company"]) for c in listed.json()] == [
        ("m1", "Acme Robotics")
    ]
    by_company = client.get(
        "/api/communications", params={"classifier_company_id": open_job["company_id"]}
    )
    assert [c["source_id"] for c in by_company.json()] == ["m1"]
    assert (
        client.get("/api/communications", params={"classifier_classification": "nope"}).status_code
        == 422
    )

    # Applied rows are left alone on later runs.
    assert sync(engine, FakeGmail([outreach("m1")]))["classifications"]["applied"] == 0


def test_classification_written_after_import_and_reclassification(mailbox):
    client, engine = mailbox
    acme = track(client, "Acme Robotics", "Director of Quality")
    fake = FakeGmail([outreach("m2")])
    assert sync(engine, fake)["classifications"]["applied"] == 0
    row, hint = stored(engine, "m2")
    assert hint is None and HINT_KEY not in row.detection

    classify(
        engine,
        "m2",
        "t-m2",
        "existing_company",
        "Acme Robotics",
        acme["company_id"],
        "0.5",
        "example-model",
        "p1",
    )
    late = sync(engine, fake)
    assert late["imported"] == 0 and late["classifications"]["applied"] == 1
    row, hint = stored(engine, "m2")
    assert row.detection[HINT_KEY]["classification"] == "existing_company"
    suggested = row.suggested_pursuit_id
    assert suggested == UUID(acme["id"])

    # The user dismisses it; then the classifier changes its mind with no companies at all.
    assert (
        client.put(f"/api/communications/{row.id}", json={"status": "dismissed"}).status_code == 200
    )
    classify(engine, "m2", "t-m2", "not_relevant", "", "", "0.2", "example-model", "p2")
    row, hint = stored(engine, "m2")
    assert hint.companies == [] and hint.company_id is None, "NULL companies become {}"
    assert hint.applied_at is None, "re-classification is applied again"
    assert sync(engine, fake)["classifications"]["applied"] == 1
    row, hint = stored(engine, "m2")
    assert row.detection[HINT_KEY]["classification"] == "not_relevant"
    assert row.detection[HINT_KEY]["prompt_version"] == "p2"
    assert row.detection[HINT_KEY]["companies"] == []
    assert row.status == "dismissed", "status is never changed"
    assert row.suggested_pursuit_id == suggested, "an existing suggestion is kept"


def test_company_hint_skips_closed_pursuits(mailbox):
    client, engine = mailbox
    open_job = track(client, "Globex", "Director of Quality")
    closed = track(client, "Globex", "Head of QA")
    # The closed one is the most recently updated, but it is no longer open.
    saved = client.put(
        f"/api/career/pursuits/{closed['id']}",
        json={"version": closed["version"], "stage": "rejected"},
    )
    assert saved.status_code == 200
    assert closed["company_id"] == open_job["company_id"]
    classify(engine, "m3", "", "opportunity", "Globex", open_job["company_id"], "0.7", "", "")
    sync(engine, FakeGmail([outreach("m3")]))
    row, _ = stored(engine, "m3")
    assert row.suggested_pursuit_id == UUID(open_job["id"])
    assert row.detection[HINT_KEY]["model"] == "", (
        "the contract stores the classifier's empty strings as given"
    )


def test_nextup_detection_wins_and_the_disagreement_is_recorded(mailbox):
    client, engine = mailbox
    classify(engine, "m4", "t-m4", "not_relevant", "", "", "0.9", "example-model", "p1")
    confirmation = message_payload(
        "m4",
        "Initech Careers <no-reply@initech.example>",
        "Thank you for applying to Initech - 1004 - Director of Quality Engineering",
        "We have received your application.",
        EPOCH,
    )
    result = sync(engine, FakeGmail([confirmation]))
    assert result["classifications"]["disagreements"] == 1
    row, _ = stored(engine, "m4")
    assert row.detection["kind"] == "application_confirmation", "Nextup's verdict stands"
    assert row.detection[HINT_KEY]["agrees"] is False
    assert row.pursuit_id is not None, "the application is still created"
    assert row.detection["applied"]["created_pursuit"] is True
    disputed = client.get("/api/communications", params={"classifier_disagrees": "true"}).json()
    assert [c["source_id"] for c in disputed] == ["m4"]


def test_rerunning_nextup_rules_keeps_the_hint_and_rechecks_agreement(mailbox):
    client, engine = mailbox
    classify(engine, "m5", "", "new_application", "Initech", "", "0.8", "example-model", "p1")
    fake = FakeGmail(
        [message_payload("m5", "Initech <no-reply@initech.example>", "Hello", "Hi.", EPOCH)]
    )
    sync(engine, fake)
    row, _ = stored(engine, "m5")
    assert row.detection["kind"] == "none" and row.detection[HINT_KEY]["agrees"] is None
    # Pretend the message was classified by older rules; the next run reclassifies it.
    with Session(engine) as session, session.begin():
        session.execute(
            text(
                "UPDATE communications SET subject = 'Thank you for applying to Initech'"
                ", detection = jsonb_set(detection, '{v}', '1') WHERE source_id = 'm5'"
            )
        )
    sync(engine, fake)
    row, _ = stored(engine, "m5")
    assert row.detection["v"] == 2 and row.detection["kind"] == "application_confirmation"
    assert row.detection[HINT_KEY]["classification"] == "new_application", "hint kept"
    assert row.detection[HINT_KEY]["agrees"] is True, "agreement recomputed"
