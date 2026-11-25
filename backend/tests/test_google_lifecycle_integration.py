"""Google lifecycle behavior across PostgreSQL sessions with synthetic provider responses."""

import os
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_gmail import FakeGmail, message_payload
from test_google_calendar import FakeCalendar, event_payload
from test_google_connection_integration import (
    BOTH_ON,
    CLIENT_ID,
    CLIENT_SECRET,
    FIRST_ADDRESS,
    HOST,
    REFRESH_TOKEN,
    SECOND_ADDRESS,
    token_response,
)
from test_google_connection_integration import connect as _connect
from test_google_connection_integration import consent as consent
from test_profile_integration import profile_client as profile_client
from test_profile_integration import profile_database as profile_database

from app import correspondence, google_connection, google_credentials, google_lifecycle, token_vault
from app.correspondence_tasks import sync_calendar, sync_gmail
from app.google_connection import REFRESH_TOKEN_PURPOSE
from app.google_consent import CALLBACK_PATH
from app.models import (
    Communication,
    Contact,
    CorrespondenceSyncSettings,
    EmailClassification,
    GoogleConnection,
    Pursuit,
)
from app.sources import gmail, google_calendar, google_oauth
from app.sources.common import SourceError

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1", reason="Requires PostgreSQL"
)
CONNECTION_PATH = "/api/google/connection"
CLIENT_PATH = "/api/google/client"
CLIENT_BODY = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
SYNC_ON = {
    "enabled": True,
    "calendar_enabled": True,
    "query": "label:synthetic",
    "max_messages_per_run": 10,
}
EDIT = {
    "subject": "Edited subject",
    "body": "Edited body",
    "notes": "User note",
    "status": "dismissed",
    "detection": {"kind": "application_confirmation", "applied": {"synthetic": True}},
}


@pytest.fixture
def connected_lifecycle(consent, monkeypatch):
    monkeypatch.setattr("app.google_actions.get_settings", lambda: BOTH_ON)
    client, google = consent
    google.token = token_response(REFRESH_TOKEN, f"{gmail.SCOPE} {google_calendar.SCOPE}")
    google.profile = httpx.Response(200, json={"emailAddress": FIRST_ADDRESS})
    google.calendar = httpx.Response(200, json={"id": FIRST_ADDRESS})
    assert _connect(client).headers["location"] == "/?google=connected"
    monkeypatch.setattr(correspondence, "get_settings", lambda: BOTH_ON)
    assert client.put("/api/correspondence", json=SYNC_ON).status_code == 200
    return client, google


def test_disconnect_commits_before_revoke_and_fences_replacement_and_old_consent(
    connected_lifecycle, profile_database, monkeypatch
):
    engine, _ = profile_database
    client, google = connected_lifecycle
    before_callback = client.post(
        "/api/google/connect",
        data={"capability": ["gmail"]},
        headers=HOST,
        follow_redirects=False,
    )
    assert before_callback.status_code == 303
    state = parse_qs(urlsplit(before_callback.headers["location"]).query)["state"][0]
    message_id, contact_id, pursuit_id = uuid4(), uuid4(), uuid4()
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                Contact(id=contact_id, name="Synthetic contact"),
                Pursuit(
                    id=pursuit_id,
                    job_key="synthetic",
                    job={"title": "Local job"},
                    created_by="user",
                ),
            ]
        )
        session.flush()
        session.add(
            Communication(
                id=message_id,
                contact_id=contact_id,
                pursuit_id=pursuit_id,
                direction="inbound",
                source="gmail",
                source_id="synthetic-message",
                **EDIT,
            )
        )

    observed = []

    def revoke(request):
        assert request.method == "POST" and str(request.url) == google_oauth.REVOCATION_URL
        assert parse_qs(request.content.decode()) == {"token": [REFRESH_TOKEN]}
        # This snapshot starts after disconnect has begun, on a separate PostgreSQL connection.
        with Session(engine) as observer:
            assert observer.get(GoogleConnection, 1) is None
            lifecycle = google_lifecycle.lifecycle_row(observer, lock=True)
            assert lifecycle.sync_paused and lifecycle.generation is None
        replacement = client.put(CLIENT_PATH, json=CLIENT_BODY)
        observed.append((replacement.status_code, replacement.json()))
        return httpx.Response(200)

    monkeypatch.setattr(
        "app.google_actions._http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(revoke)),
    )
    result = client.delete(CONNECTION_PATH)
    assert result.status_code == 200
    assert result.json()["revocation"] == "confirmed"
    assert observed == [
        (409, {"detail": {"code": "busy", "message": google_lifecycle.BUSY_MESSAGE}})
    ]
    with Session(engine) as observer:
        row = observer.get(Communication, message_id)
        assert {key: getattr(row, key) for key in EDIT} == EDIT
        assert (row.contact_id, row.pursuit_id) == (contact_id, pursuit_id)

    # The same OAuth client ID cannot revive a flow started before disconnect.
    assert client.put(CLIENT_PATH, json=CLIENT_BODY).status_code == 200
    before_provider = len(google.requests)
    old_callback = client.get(
        CALLBACK_PATH,
        params={"state": state, "code": "synthetic-code"},
        headers=HOST,
        follow_redirects=False,
    )
    assert old_callback.headers["location"] == "/?google=failed"
    assert len(google.requests) == before_provider
    with Session(engine) as observer:
        assert observer.get(GoogleConnection, 1).state == "not_connected"


def test_disconnect_does_not_revoke_or_restart_a_possibly_shared_fallback(
    connected_lifecycle, profile_database, monkeypatch
):
    engine, _ = profile_database
    client, _google = connected_lifecycle
    fallback = BOTH_ON.model_copy(
        update={
            "google_oauth_client_id": SecretStr(CLIENT_ID),
            "google_oauth_client_secret": SecretStr("synthetic-fallback-secret"),
            "gmail_refresh_token": SecretStr("synthetic-fallback-token"),
        }
    )
    monkeypatch.setattr("app.google_actions.get_settings", lambda: fallback)
    monkeypatch.setattr(google_connection, "get_settings", lambda: fallback)
    monkeypatch.setattr(correspondence, "get_settings", lambda: fallback)

    provider_calls = []

    def refused_call(*args):
        provider_calls.append("provider_called")
        raise AssertionError("No provider call was expected")

    monkeypatch.setattr(
        "app.google_actions._http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(refused_call)),
    )
    response = client.delete(CONNECTION_PATH)
    assert response.status_code == 200
    result = response.json()
    assert result["revocation"] == "unconfirmed"
    assert result["connection"]["credential_source"] == "configured"
    assert all(not status["active"] for status in result["connection"]["sync"].values())
    with httpx.Client(transport=httpx.MockTransport(refused_call)) as http:
        for sync in (sync_gmail, sync_calendar):
            with Session(engine) as session, session.begin():
                assert sync(session, fallback, client=http)["status"] == "disabled"
    assert provider_calls == []
    assert client.put("/api/correspondence", json=SYNC_ON).status_code == 200
    status = client.get(CONNECTION_PATH).json()
    assert all(value["active"] for value in status["sync"].values())


def test_invalid_grant_marks_only_the_current_generation(connected_lifecycle, profile_database):
    engine, _ = profile_database
    client, _google = connected_lifecycle

    def invalid_grant(request):
        assert request.method == "POST" and str(request.url) == google_oauth.TOKEN_URL
        return httpx.Response(400, json={"error": "invalid_grant"})

    def replace_before_returning_invalid_grant(request):
        with Session(engine) as other, other.begin():
            lifecycle = google_lifecycle.lifecycle_row(other, lock=True)
            row = other.get(GoogleConnection, 1, with_for_update=True)
            row.refresh_token_sealed = token_vault.seal(
                "synthetic-replacement-token", purpose=REFRESH_TOKEN_PURPOSE, settings=BOTH_ON
            )
            google_lifecycle.advance_generation(lifecycle)
        return invalid_grant(request)

    for provider, expected_state in (
        (replace_before_returning_invalid_grant, "connected"),
        (invalid_grant, "needs_reauthorization"),
    ):
        with (
            Session(engine) as session,
            httpx.Client(transport=httpx.MockTransport(provider)) as http,
        ):
            credentials = google_credentials.resolve(session, BOTH_ON, "gmail")
            with pytest.raises(SourceError):
                google_credentials.access_token(http, session, BOTH_ON, credentials, "gmail")
        report = client.get(CONNECTION_PATH).json()
        assert report["state"] == expected_state
    assert all(not status["active"] for status in report["sync"].values())


def test_admitted_result_cannot_import_after_disconnect(
    connected_lifecycle, profile_database, monkeypatch
):
    engine, _ = profile_database
    client, _ = connected_lifecycle
    fake = FakeGmail([message_payload("late", "team@example.test", "Synthetic", "", 1700000000000)])
    monkeypatch.setattr(
        "app.google_actions._http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200))),
    )

    def provider(request):
        if request.url.path.endswith("/messages/late"):
            # This independent lifecycle action must finish while the worker still owns
            # the sync-settings lock and waits on the admitted provider call.
            result = client.delete(CONNECTION_PATH)
            assert result.status_code == 200 and result.json()["result"] == "disconnected"
        return fake.handler(request)

    with (
        Session(engine) as session,
        session.begin(),
        httpx.Client(transport=httpx.MockTransport(provider)) as http,
    ):
        assert sync_gmail(session, BOTH_ON, http, intake=True) == {
            "status": "disabled",
            "imported": 0,
        }
    with Session(engine) as observer:
        assert observer.scalars(select(Communication)).all() == []
        config = observer.get(CorrespondenceSyncSettings, 1)
        assert config.cursor_epoch is config.last_run_at is None
        row = google_lifecycle.lifecycle_row(observer)
        assert row.sync_paused and row.gmail_attempt_generation is row.gmail_last_success_at is None


def test_replacement_leaves_legacy_rows_classifier_and_user_decisions_untouched(
    connected_lifecycle, profile_database
):
    engine, _ = profile_database
    client, google = connected_lifecycle
    past = datetime(2020, 1, 1, tzinfo=UTC)
    legacy_mail, confirmation, legacy_event = (uuid4() for _ in range(3))
    with Session(engine) as session, session.begin():
        config = session.get(CorrespondenceSyncSettings, 1)
        config.auto_create_applications = True
        config.cursor_epoch = 123
        session.add_all(
            [
                Communication(
                    id=legacy_mail,
                    source="gmail",
                    source_id="collision",
                    direction="inbound",
                    status="dismissed",
                    sender=SECOND_ADDRESS,
                    subject="Edited subject",
                    body="Edited body",
                    created_at=past,
                ),
                Communication(
                    id=confirmation,
                    source="gmail",
                    source_id="old-confirmation",
                    direction="inbound",
                    status="received",
                    created_at=past,
                    detection={
                        "v": 2,
                        "kind": "application_confirmation",
                        "confidence": "high",
                        "company": "Synthetic",
                        "title": "Old role",
                    },
                ),
                Communication(
                    id=legacy_event,
                    source="calendar",
                    source_id="collision",
                    direction="note",
                    status="dismissed",
                    notes="Edited notes",
                    subject="Edited event",
                    created_at=past,
                ),
                EmailClassification(
                    gmail_message_id="new", classification="opportunity", classified_at=past
                ),
            ]
        )

    google.token = token_response("synthetic-replacement", f"{gmail.SCOPE} {google_calendar.SCOPE}")
    google.profile = httpx.Response(200, json={"emailAddress": SECOND_ADDRESS})
    google.calendar = httpx.Response(200, json={"id": SECOND_ADDRESS})
    assert _connect(client).headers["location"] == "/?google=connected"
    fake_mail = FakeGmail(
        [
            message_payload(key, "team@example.test", "Synthetic", "", 1700000000000)
            for key in ("collision", "new")
        ],
        owner=SECOND_ADDRESS,
    )
    fake_calendar = FakeCalendar(
        [event_payload("collision", "Another mailbox", "2026-11-24T12:00:00Z")]
    )
    for expected in (1, 0):
        with Session(engine) as session, session.begin(), fake_mail.client() as http:
            result = sync_gmail(session, BOTH_ON, http, intake=True)
            assert result["imported"] == expected and result["applications"]["created"] == 0
        with Session(engine) as session, session.begin(), fake_calendar.client() as http:
            assert sync_calendar(session, BOTH_ON, http) == {
                "status": "ok",
                "imported": 0,
                "updated": 0,
            }
    assert not any(request.url.path.endswith("/profile") for request in fake_mail.requests)
    assert all(
        "after:123" not in r.url.params["q"] for r in fake_mail.requests if "q" in r.url.params
    )
    with Session(engine) as observer:
        mail = observer.get(Communication, legacy_mail)
        assert (mail.direction, mail.status, mail.subject, mail.body, mail.detection) == (
            "inbound",
            "dismissed",
            "Edited subject",
            "Edited body",
            None,
        )
        assert observer.get(Communication, confirmation).pursuit_id is None
        event = observer.get(Communication, legacy_event)
        assert (event.subject, event.status, event.notes, event.detection) == (
            "Edited event",
            "dismissed",
            "Edited notes",
            None,
        )
        assert observer.get(EmailClassification, "new").applied_at is None
        lifecycle = google_lifecycle.lifecycle_row(observer)
        assert lifecycle.gmail_last_success_at is lifecycle.calendar_last_success_at is None
        assert (
            lifecycle.gmail_attempt_generation
            == lifecycle.calendar_attempt_generation
            == lifecycle.generation
        )
