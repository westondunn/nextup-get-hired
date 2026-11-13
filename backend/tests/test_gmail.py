"""Gmail adapter and sync logic with a mocked provider; no real mailbox is touched."""

# The public webmail and applicant-tracking domains in this file are intentional: mail
# detection keys on those exact domains, so a reserved example domain would not exercise
# it. Every local part, name and message body is synthetic.

import base64
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.correspondence_tasks import suggest_pursuit, sync_gmail
from app.db import get_session
from app.main import app
from app.models import Communication, Contact, CorrespondenceSyncSettings, Pursuit
from app.sources import gmail
from app.sources.common import SourceError

CONFIGURED = Settings(
    gmail_sync_enabled=True,
    google_oauth_client_id=SecretStr("client"),
    google_oauth_client_secret=SecretStr("secret"),
    gmail_refresh_token=SecretStr("refresh"),
)


def b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def message_payload(message_id, sender, subject, body, epoch_ms, html=False, labels=(), headers=()):
    part = {
        "mimeType": "text/html" if html else "text/plain",
        "body": {"data": b64(body)},
    }
    return {
        "id": message_id,
        "threadId": f"t-{message_id}",
        "internalDate": str(epoch_ms),
        "snippet": "snippet",
        "labelIds": list(labels),
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
                *({"name": name, "value": value} for name, value in headers),
            ],
            "parts": [part],
        },
    }


class FakeGmail:
    """Serves token refresh, list, and get requests through httpx's mock transport."""

    def __init__(self, messages, scope=gmail.SCOPE, owner="me@example.test"):
        self.messages = {m["id"]: m for m in messages}
        self.owner = owner
        self.scope = scope
        self.requests = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url == gmail.TOKEN_URL:
            return httpx.Response(200, json={"access_token": "token", "scope": self.scope})
        assert request.headers["Authorization"] == "Bearer token"
        if request.url.path.endswith("/profile"):
            return httpx.Response(200, json={"emailAddress": self.owner})
        if request.url.path.endswith("/messages"):
            return httpx.Response(
                200,
                json={"messages": [{"id": i, "threadId": f"t-{i}"} for i in self.messages]},
            )
        message_id = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=self.messages[message_id])

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def test_parse_message_prefers_plain_text_and_bounds_fields():
    payload = message_payload(
        "m1",
        "Riley Recruiter <Riley@Example.com>",
        "Next steps",
        "Hello\x00 there",
        1_700_000_000_000,
    )
    parsed = gmail.parse_message(payload)
    assert parsed.sender_email == "riley@example.com"
    assert parsed.sender_name == "Riley Recruiter"
    assert parsed.body == "Hello there"
    assert parsed.received_at == datetime.fromtimestamp(1_700_000_000, tz=UTC)
    assert parsed.thread_id == "t-m1"


def test_parse_message_falls_back_to_html_then_snippet():
    html = message_payload("m2", "a@b.example", "s", "<p>Hi <b>there</b></p>", 1, html=True)
    assert gmail.parse_message(html).body == "Hi there"
    empty = {"id": "m3", "internalDate": "bad", "snippet": "only snippet", "payload": {}}
    parsed = gmail.parse_message(empty)
    assert parsed.body == "only snippet"
    assert parsed.sender_email == ""


def test_refresh_requires_credentials_and_readonly_scope():
    with pytest.raises(SourceError) as excinfo:
        gmail.refresh_access_token(httpx.Client(), Settings())
    assert excinfo.value.code == "not_configured"
    with FakeGmail([], scope="https://mail.google.com/").client() as client:
        with pytest.raises(SourceError) as excinfo:
            gmail.refresh_access_token(client, CONFIGURED)
    assert excinfo.value.code == "wrong_scope"


@pytest.mark.parametrize(
    "status,code",
    [(401, "unauthorized"), (429, "provider_unavailable"), (503, "provider_unavailable")],
)
def test_provider_errors_are_classified(status, code):
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json={}))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(SourceError) as excinfo:
            gmail.list_message_refs(client, "token", "label:x", 10)
    assert excinfo.value.code == code


def test_list_message_refs_honors_limit_and_pages():
    pages = {
        None: {"messages": [{"id": "a"}, {"id": "b"}], "nextPageToken": "p2"},
        "p2": {"messages": [{"id": "c"}, {"id": "d"}]},
    }

    def handler(request):
        return httpx.Response(200, json=pages[request.url.params.get("pageToken")])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert [i for i, _ in gmail.list_message_refs(client, "t", "q", 3)] == ["a", "b", "c"]
        assert len(gmail.list_message_refs(client, "t", "q", 10)) == 4


def pursuit(company):
    return Pursuit(id=uuid4(), job_key=company, job={"company": company}, stage="applied")


def parsed(sender_email, subject="", sender_name="", body=""):
    return gmail.ParsedMessage(
        "id", "t", sender_name, sender_email, subject, body, datetime.now(UTC)
    )


def test_suggest_pursuit_uses_domain_then_subject_and_ignores_generic_domains():
    acme, globex = pursuit("Acme Robotics"), pursuit("Globex")
    # A country-code suffix is the point of this case, so it cannot use a reserved domain.
    assert suggest_pursuit(parsed("hr@mail.acme-robotics.co.uk"), [acme, globex]) is acme
    assert suggest_pursuit(parsed("hr@mail.acme.test"), [acme, globex]) is acme
    assert suggest_pursuit(parsed("hr@acmerobotics.example"), [acme, globex]) is acme
    assert suggest_pursuit(parsed("hr@acme.example"), [acme, globex]) is acme
    assert suggest_pursuit(parsed("x@gmail.com", "Your Globex interview"), [acme, globex]) is globex
    assert suggest_pursuit(parsed("x@greenhouse.io", "Hello"), [acme, globex]) is None
    assert suggest_pursuit(parsed("x@acme.example"), []) is None


def test_suggest_pursuit_reads_tracking_mailers_recruiter_subjects_and_bodies():
    northwind, brightwell, peak = (
        pursuit("Harlow Northwind"),
        pursuit("Brightwell Financial"),
        pursuit("Global Peak"),
    )
    rows = [northwind, brightwell, peak]
    # An applicant-tracking mailbox names the employer in its display name, not its domain.
    tracked = parsed(
        "northwind+email+0000a@talent.icims.com",
        "Your Phone Interview has been confirmed!",
        "Harlow Northwind Corporation @ icims",
    )
    assert suggest_pursuit(tracked, rows) is northwind
    assert suggest_pursuit(parsed("x@talent.icims.com", "Hello"), rows) is None
    # One distinctive word of the name is enough in a subject.
    assert (
        suggest_pursuit(parsed("r@staffing.example", "Northwind interview times"), rows)
        is northwind
    )
    assert (
        suggest_pursuit(parsed("r@staffing.example", "Sam [Brightwell] - Resume (2026)"), rows)
        is brightwell
    )
    # Common words never stand for an employer; the full name still does.
    assert suggest_pursuit(parsed("r@staffing.example", "Global markets role"), rows) is None
    assert suggest_pursuit(parsed("r@staffing.example", "Global Peak update"), rows) is peak
    # The body is the weakest evidence and still beats nothing.
    in_body = parsed("r@staffing.example", "Quick question", body="My client Brightwell Financial")
    assert suggest_pursuit(in_body, rows) is brightwell
    # Weak evidence naming two employers suggests nothing; the sender's domain decides.
    both = "Northwind and Brightwell openings"
    assert suggest_pursuit(parsed("r@staffing.example", both), rows) is None
    assert suggest_pursuit(parsed("r@northwind.example", both), rows) is northwind


def fake_session(config, contacts=(), pursuits=(), known=(), unclassified=()):
    """A MagicMock session that answers the four queries the sync performs."""
    session = MagicMock()
    session.get.return_value = config
    session.added = []
    session.add.side_effect = session.added.append

    def scalars(statement):
        text = str(statement)
        result = MagicMock()
        if "communications.detection IS NULL" in text:
            result.all.return_value = list(unclassified)
        elif "communications.source_id" in text:
            result.all.return_value = list(known)
        elif "contacts" in text:
            result.all.return_value = list(contacts)
        else:
            result.all.return_value = list(pursuits)
        return result

    session.scalars.side_effect = scalars
    return session


def test_sync_skips_when_disabled_or_not_configured():
    session = fake_session(None)
    assert sync_gmail(session, CONFIGURED, client=httpx.Client()) == {
        "status": "disabled",
        "imported": 0,
    }
    config = CorrespondenceSyncSettings(id=1, enabled=True, query="label:x", max_messages_per_run=5)
    session = fake_session(config)
    assert sync_gmail(session, Settings(), client=httpx.Client())["status"] == "not_configured"
    assert config.last_status == "not_configured"
    assert session.added == []


def test_sync_imports_links_contacts_suggests_pursuits_and_advances_cursor():
    contact = Contact(id=uuid4(), name="Riley", email="Riley@Acme.example")
    acme = pursuit("Acme")
    fake = FakeGmail(
        [
            message_payload(
                "m1", "Riley <riley@acme.example>", "Next steps", "Body one", 1_700_000_000_000
            ),
            message_payload(
                "m2", "noreply@gmail.com", "Globex update", "Body two", 1_700_000_500_000
            ),
            message_payload("old", "x@y.z", "already stored", "dup", 1_600_000_000_000),
        ]
    )
    config = CorrespondenceSyncSettings(id=1, enabled=True, query="label:x", max_messages_per_run=5)
    session = fake_session(config, contacts=[contact], pursuits=[acme], known=["old"])
    with fake.client() as client:
        result = sync_gmail(session, CONFIGURED, client=client, now=datetime.now(UTC))
    assert result == {
        "status": "ok",
        "imported": 2,
        "remaining": 0,
        "classifications": {"applied": 0, "suggested": 0, "disagreements": 0},
    }
    rows = {row.source_id: row for row in session.added}
    assert set(rows) == {"m1", "m2"}
    assert rows["m1"].contact_id == contact.id
    assert rows["m1"].suggested_pursuit_id == acme.id
    assert rows["m1"].pursuit_id is None, "pursuits are suggested, never auto-linked"
    assert rows["m1"].direction == "inbound" and rows["m1"].status == "received"
    assert rows["m1"].sender == "Riley <riley@acme.example>"
    assert rows["m2"].contact_id is None and rows["m2"].suggested_pursuit_id is None
    assert config.cursor_epoch == 1_700_000_500 and config.last_status == "ok"
    listing = next(r for r in fake.requests if r.url.path.endswith("/messages"))
    assert "label:x after:" in listing.url.params["q"]
    fetched = [r.url.path.rsplit("/", 1)[-1] for r in fake.requests if "/messages/" in r.url.path]
    assert fetched == ["m1", "m2"], "known messages are never fetched again"


def test_parse_message_reads_sent_label_recipient_and_auto_reply_header():
    sent = gmail.parse_message(
        message_payload(
            "s1",
            "Me <me@example.test>",
            "Re: Hi",
            "b",
            1,
            labels=["SENT"],
            headers=[("To", "Riley <Riley@Acme.example>")],
        )
    )
    assert sent.is_sent and sent.recipient_email == "riley@acme.example" and not sent.auto_reply
    away = gmail.parse_message(
        message_payload(
            "a1", "r@acme.example", "Away", "b", 1, headers=[("Auto-Submitted", "auto-replied")]
        )
    )
    assert away.auto_reply and not away.is_sent
    generated = gmail.parse_message(
        message_payload(
            "c1", "r@acme.example", "s", "b", 1, headers=[("Auto-Submitted", "auto-generated")]
        )
    )
    assert not generated.auto_reply, "confirmations are auto-generated, not automatic replies"


def test_sync_logs_own_mail_as_sent_and_classifies_new_and_stored_mail():
    contact = Contact(id=uuid4(), name="Riley", email="riley@acme.example")
    fake = FakeGmail(
        [
            message_payload(
                "own",
                "Me <me@example.test>",
                "Re: Next steps",
                "Sure",
                1_700_000_000_000,
                labels=["SENT"],
                headers=[("To", "riley@acme.example")],
            ),
            message_payload(
                "conf",
                "Acme Careers <no-reply@acme.example>",
                "Thank you for applying to Acme - 1004 - Director, Quality Engineering",
                "We received your application.",
                1_700_000_100_000,
            ),
            message_payload(
                "away",
                "Riley <riley@acme.example>",
                "Automatic reply: Next steps",
                "Out.",
                1_700_000_200_000,
            ),
        ]
    )
    legacy_own = Communication(
        id=uuid4(),
        source="gmail",
        direction="inbound",
        status="received",
        sender="Me <ME@example.test>",
        subject="Re: Next steps",
        body="",
        received_at=datetime(2026, 11, 1, tzinfo=UTC),
    )
    legacy_confirmation = Communication(
        id=uuid4(),
        source="gmail",
        direction="inbound",
        status="received",
        sender="talent@globex.example",
        subject="You have successfully submitted your Globex job application",
        body="",
        received_at=datetime(2026, 11, 1, tzinfo=UTC),
    )
    config = CorrespondenceSyncSettings(id=1, enabled=True, query="label:x", max_messages_per_run=5)
    session = fake_session(
        config, contacts=[contact], unclassified=[legacy_own, legacy_confirmation]
    )
    with fake.client() as client:
        assert sync_gmail(session, CONFIGURED, client=client)["imported"] == 3
    rows = {row.source_id: row for row in session.added}
    assert (rows["own"].direction, rows["own"].status) == ("outbound", "sent")
    assert rows["own"].sent_at == rows["own"].received_at
    assert rows["own"].contact_id == contact.id, "sent mail links by its recipient"
    assert rows["own"].detection == {"v": 2, "kind": "none"}
    assert rows["conf"].detection == {
        "v": 2,
        "kind": "application_confirmation",
        "confidence": "high",
        "company": "Acme",
        "title": "Director, Quality Engineering",
        "requisition": "1004",
        "evidence": "Thank you for applying",
    }
    assert rows["conf"].pursuit_id is None, "the sync classifies; intake acts separately"
    assert rows["away"].detection["kind"] == "auto_reply"
    assert (legacy_own.direction, legacy_own.status) == ("outbound", "sent")
    assert legacy_own.sent_at == legacy_own.received_at
    assert legacy_confirmation.direction == "inbound"
    assert legacy_confirmation.detection["company"] == "Globex"
    assert legacy_confirmation.detection["confidence"] == "medium", "no role was named"


def test_sync_batch_limit_keeps_cursor_until_backlog_is_drained():
    fake = FakeGmail(
        [message_payload(f"m{n}", "a@b.c", "s", "b", 1_700_000_000_000 + n) for n in range(3)]
    )
    config = CorrespondenceSyncSettings(
        id=1, enabled=True, query="label:x", max_messages_per_run=2, cursor_epoch=1_650_000_000
    )
    session = fake_session(config)
    with fake.client() as client:
        result = sync_gmail(session, CONFIGURED, client=client)
    assert result == {
        "status": "ok",
        "imported": 2,
        "remaining": 1,
        "classifications": {"applied": 0, "suggested": 0, "disagreements": 0},
    }
    assert config.cursor_epoch == 1_650_000_000, "cursor must not skip the unfetched message"


def test_sync_records_provider_failure_without_raising():
    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    config = CorrespondenceSyncSettings(id=1, enabled=True, query="label:x", max_messages_per_run=2)
    session = fake_session(config)
    with httpx.Client(transport=transport) as client:
        result = sync_gmail(session, CONFIGURED, client=client)
    assert result["status"] == "provider_unavailable"
    assert config.last_status == "provider_unavailable" and "unavailable" in config.last_error
    assert session.added == []


@pytest.fixture
def api_session():
    database = MagicMock()
    database.get.return_value = None
    database.scalar.return_value = 0
    app.dependency_overrides[get_session] = lambda: database
    yield database
    app.dependency_overrides.clear()


def test_settings_api_refuses_to_enable_without_local_credentials(api_session, monkeypatch):
    monkeypatch.setattr("app.correspondence.get_settings", lambda: Settings())
    client = TestClient(app)
    body = client.get("/api/correspondence").json()
    assert body["enabled"] is False and body["credentials_present"] is False
    assert body["live_enabled"] is False and body["review_count"] == 0
    response = client.put(
        "/api/correspondence",
        json={"enabled": True, "query": "label:job-search", "max_messages_per_run": 25},
    )
    assert response.status_code == 409
    api_session.commit.assert_not_called()
    assert client.post("/api/correspondence/sync").status_code == 409


def test_settings_api_rejects_bad_query(api_session):
    client = TestClient(app)
    response = client.put(
        "/api/correspondence", json={"enabled": False, "query": "a\nb", "max_messages_per_run": 1}
    )
    assert response.status_code == 422
    assert json.loads(response.content)["detail"]
