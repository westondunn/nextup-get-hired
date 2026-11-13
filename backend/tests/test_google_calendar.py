"""Calendar adapter and sync with a mocked provider; no real calendar is touched."""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.correspondence_tasks import sync_calendar
from app.db import get_session
from app.main import app
from app.models import Contact, CorrespondenceSyncSettings, Pursuit
from app.sources import google_calendar as cal
from app.sources.common import SourceError

CONFIGURED = Settings(
    calendar_sync_enabled=True,
    google_oauth_client_id=SecretStr("client"),
    google_oauth_client_secret=SecretStr("secret"),
    gmail_refresh_token=SecretStr("refresh"),
)
BOTH_SCOPES = f"{cal.SCOPE} https://www.googleapis.com/auth/gmail.readonly"


def event_payload(event_id, summary, start, attendees=(), **extra):
    return {
        "id": event_id,
        "status": "confirmed",
        "summary": summary,
        "start": {"dateTime": start},
        "end": {"dateTime": start},
        "organizer": {"email": "me@example.com", "displayName": "Me", "self": True},
        "attendees": [{"email": "me@example.com", "self": True}]
        + [{"email": email, "displayName": name} for email, name in attendees],
        **extra,
    }


class FakeCalendar:
    def __init__(self, items, scope=BOTH_SCOPES):
        self.items = items
        self.scope = scope
        self.requests = []

    def handler(self, request):
        self.requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "token", "scope": self.scope})
        assert request.headers["Authorization"] == "Bearer token"
        assert request.url.params["singleEvents"] == "true"
        return httpx.Response(200, json={"items": self.items})

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def test_parse_event_handles_timed_all_day_cancelled_and_malformed():
    timed = cal.parse_event(
        event_payload(
            "e1",
            "Interview",
            "2026-11-10T15:00:00-05:00",
            [("riley@acme.example", "Riley")],
            description="<p>Panel <b>round</b></p>",
            location="https://meet.example/abc",
            hangoutLink="https://meet.example/abc",
        )
    )
    assert timed.starts_at == datetime(2026, 11, 10, 20, 0, tzinfo=UTC)
    assert timed.attendee_emails == ("riley@acme.example",) and timed.attendee_names == ("Riley",)
    assert timed.description == "Panel round" and timed.link == "https://meet.example/abc"
    all_day = cal.parse_event({"id": "e2", "start": {"date": "2026-11-12"}})
    assert all_day.all_day and all_day.starts_at == datetime(2026, 11, 12, tzinfo=UTC)
    assert (
        cal.parse_event({"id": "e3", "status": "cancelled", "start": {"date": "2026-11-12"}})
        is None
    )
    assert cal.parse_event({"id": "e4"}) is None
    assert cal.parse_event({"start": {"date": "2026-11-12"}}) is None


def test_refresh_requires_calendar_scope():
    with FakeCalendar([], scope="https://www.googleapis.com/auth/gmail.readonly").client() as c:
        with pytest.raises(SourceError) as excinfo:
            cal.refresh_access_token(c, CONFIGURED)
    assert excinfo.value.code == "wrong_scope"
    with pytest.raises(SourceError) as excinfo:
        cal.refresh_access_token(httpx.Client(), Settings())
    assert excinfo.value.code == "not_configured"


def test_list_events_sends_utc_window_and_rejects_bad_payload():
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(200, json={"items": "nope"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError):
            cal.list_events(
                client,
                "t",
                datetime(2026, 11, 1, tzinfo=UTC),
                datetime(2026, 11, 15, tzinfo=UTC),
                max_events=500,
            )
    assert seen["timeMin"] == "2026-11-01T00:00:00Z" and seen["maxResults"] == "100"


def fake_session(config, contacts=(), pursuits=(), existing=()):
    session = MagicMock()
    session.get.return_value = config
    session.added = []
    session.add.side_effect = session.added.append

    def scalars(statement):
        text = str(statement)
        result = MagicMock()
        if "communications" in text:
            result.all.return_value = list(existing)
        elif "contacts" in text:
            result.all.return_value = list(contacts)
        else:
            result.all.return_value = list(pursuits)
        return result

    session.scalars.side_effect = scalars
    return session


def test_sync_calendar_skips_when_disabled_or_not_configured():
    assert sync_calendar(fake_session(None), CONFIGURED, client=httpx.Client())["status"] == (
        "disabled"
    )
    config = CorrespondenceSyncSettings(id=1, calendar_enabled=True, calendar_lookahead_days=7)
    session = fake_session(config)
    assert sync_calendar(session, Settings(), client=httpx.Client())["status"] == "not_configured"
    assert config.calendar_last_status == "not_configured" and session.added == []


def test_sync_calendar_imports_links_contacts_suggests_pursuits_and_updates_changes():
    contact = Contact(id=uuid4(), name="Riley", email="Riley@Acme.example")
    acme = Pursuit(id=uuid4(), job_key="acme", job={"company": "Acme"}, stage="interview")
    fake = FakeCalendar(
        [
            event_payload(
                "e1",
                "Acme panel interview",
                "2026-11-10T15:00:00Z",
                [("riley@acme.example", "Riley")],
                hangoutLink="https://meet.example/x",
            ),
            event_payload(
                "e2", "Dentist", "2026-11-11T15:00:00Z", location="12 Main St, Springfield"
            ),
            {"id": "gone", "status": "cancelled", "start": {"date": "2026-11-12"}},
        ]
    )
    config = CorrespondenceSyncSettings(id=1, calendar_enabled=True, calendar_lookahead_days=14)
    session = fake_session(config, contacts=[contact], pursuits=[acme])
    now = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
    with fake.client() as client:
        result = sync_calendar(session, CONFIGURED, client=client, now=now)
    assert result == {"status": "ok", "imported": 2, "updated": 0}
    rows = {row.source_id: row for row in session.added}
    assert rows["e1"].contact_id == contact.id and rows["e1"].suggested_pursuit_id == acme.id
    assert rows["e1"].pursuit_id is None and rows["e1"].channel == "other"
    assert rows["e1"].direction == "note" and rows["e1"].status == "private_note"
    assert rows["e1"].received_at == datetime(2026, 11, 10, 15, 0, tzinfo=UTC)
    assert "Link: https://meet.example/x" in rows["e1"].body and "Riley" in rows["e1"].body
    assert "interview" in rows["e1"].notes.lower()
    assert rows["e2"].channel == "in_person" and rows["e2"].contact_id is None
    assert rows["e2"].suggested_pursuit_id is None
    assert config.calendar_last_status == "ok" and config.calendar_last_imported == 2
    listing = next(r for r in fake.requests if r.url.host == "www.googleapis.com")
    assert listing.url.params["timeMin"] == "2026-11-03T12:00:00Z"
    assert listing.url.params["timeMax"] == "2026-11-18T12:00:00Z"

    # A rescheduled event updates the stored row instead of duplicating it.
    stored = rows["e1"]
    moved = FakeCalendar([event_payload("e1", "Acme panel interview", "2026-11-12T15:00:00Z")])
    session = fake_session(config, existing=[stored])
    with moved.client() as client:
        result = sync_calendar(session, CONFIGURED, client=client, now=now)
    assert result == {"status": "ok", "imported": 0, "updated": 1}
    assert stored.received_at == datetime(2026, 11, 12, 15, 0, tzinfo=UTC)
    assert session.added == []


def test_sync_calendar_records_provider_failure():
    transport = httpx.MockTransport(lambda request: httpx.Response(403))
    config = CorrespondenceSyncSettings(id=1, calendar_enabled=True, calendar_lookahead_days=14)
    session = fake_session(config)
    with httpx.Client(transport=transport) as client:
        assert sync_calendar(session, CONFIGURED, client=client)["status"] == "unauthorized"
    assert config.calendar_last_status == "unauthorized" and session.added == []


@pytest.fixture
def api_session():
    database = MagicMock()
    database.get.return_value = None
    database.scalar.return_value = 0
    app.dependency_overrides[get_session] = lambda: database
    yield database
    app.dependency_overrides.clear()


def test_settings_api_refuses_calendar_without_credentials(api_session, monkeypatch):
    monkeypatch.setattr("app.correspondence.get_settings", lambda: Settings())
    client = TestClient(app)
    body = client.get("/api/correspondence").json()
    assert body["calendar_enabled"] is False and body["calendar_live_enabled"] is False
    assert body["calendar_last_status"] == "not_run"
    response = client.put(
        "/api/correspondence",
        json={
            "enabled": False,
            "query": "label:job-search",
            "max_messages_per_run": 25,
            "calendar_enabled": True,
            "calendar_lookahead_days": 14,
        },
    )
    assert (
        response.status_code == 409 and "Calendar sync is switched off" in response.json()["detail"]
    )
    api_session.commit.assert_not_called()
