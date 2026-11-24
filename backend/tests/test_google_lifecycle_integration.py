"""Google lifecycle behavior across PostgreSQL sessions with synthetic provider responses."""

import os
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.orm import Session
from test_google_connection_integration import (
    BOTH_ON,
    CLIENT_ID,
    CLIENT_SECRET,
    FIRST_ADDRESS,
    HOST,
    REFRESH_TOKEN,
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
from app.models import Communication, Contact, GoogleConnection, Pursuit
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
