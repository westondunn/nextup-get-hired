"""The stored Google connection, written and read by the runtime role.

First through the model, then through the routes that save and report the user's client,
then through the consent flow with every Google call mocked.
"""

import os
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from test_google_consent import Google, Redis
from test_profile_integration import profile_client as profile_client
from test_profile_integration import profile_database as profile_database

from app import google_connection, google_consent, token_vault
from app.config import Settings
from app.google_connection import CLIENT_IN_USE, CLIENT_SECRET_PURPOSE, REFRESH_TOKEN_PURPOSE
from app.google_consent import CALLBACK_PATH, FLOW_REFUSED, FlowStore, get_flow_store
from app.main import app
from app.models import GoogleConnection
from app.sources import gmail, google_calendar, google_oauth

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1", reason="Requires PostgreSQL"
)
# The tests service has no token key of its own; this one exists only here.
KEY = Settings(token_key=SecretStr("integration-test-only-token-key-0123456789abcd"))
CLIENT_SECRET = "synthetic-client-secret"
REFRESH_TOKEN = "synthetic-refresh-token"
SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


def seal(value, purpose):
    return token_vault.seal(value, purpose=purpose, settings=KEY)


def test_runtime_role_stores_reads_and_removes_the_connection(profile_database):
    engine, _ = profile_database
    with Session(engine) as session, session.begin():
        session.add(
            GoogleConnection(
                id=1,
                client_id="synthetic-client",
                client_secret_sealed=seal(CLIENT_SECRET, "google.client_secret"),
            )
        )
    with Session(engine) as session, session.begin():
        row = session.get(GoogleConnection, 1)
        assert (row.state, row.key_version, row.granted_scopes) == ("not_connected", 1, [])
        assert row.refresh_token_sealed is None and row.connected_at is None
        assert row.created_at is not None and row.updated_at is not None
        row.refresh_token_sealed = seal(REFRESH_TOKEN, "google.refresh_token")
        row.state = "connected"
        row.granted_scopes = [SCOPE]
        row.account_address = "synthetic.user@example.invalid"
    with Session(engine) as session, session.begin():
        row = session.get(GoogleConnection, 1)
        assert (row.state, row.granted_scopes) == ("connected", [SCOPE])
        # Neither credential is in the table as plain text, and both open with the key.
        assert CLIENT_SECRET not in row.client_secret_sealed
        assert REFRESH_TOKEN not in row.refresh_token_sealed
        opened = token_vault.open_sealed(
            row.client_secret_sealed, purpose="google.client_secret", settings=KEY
        )
        assert opened == CLIENT_SECRET
        opened = token_vault.open_sealed(
            row.refresh_token_sealed, purpose="google.refresh_token", settings=KEY
        )
        assert opened == REFRESH_TOKEN
        session.delete(row)
    with Session(engine) as session:
        assert session.get(GoogleConnection, 1) is None


def test_the_model_cannot_store_a_plain_credential_or_a_second_connection(profile_database):
    engine, _ = profile_database
    sealed = seal(CLIENT_SECRET, "google.client_secret")
    for attempt in (
        dict(id=1, client_id="synthetic-client", client_secret_sealed=CLIENT_SECRET),
        dict(id=2, client_id="synthetic-client", client_secret_sealed=sealed),
        dict(
            id=1,
            client_id="synthetic-client",
            client_secret_sealed=sealed,
            refresh_token_sealed=REFRESH_TOKEN,
            state="connected",
        ),
        dict(id=1, client_id="synthetic-client", client_secret_sealed=sealed, state="connected"),
    ):
        with pytest.raises(IntegrityError):
            with Session(engine) as session, session.begin():
                session.add(GoogleConnection(**attempt))
    with Session(engine) as session:
        assert session.scalars(select(GoogleConnection)).all() == []


def test_a_change_to_the_connection_holds_the_row_lock(profile_database):
    engine, _ = profile_database
    with Session(engine) as session, session.begin():
        session.add(
            GoogleConnection(
                id=1,
                client_id="synthetic-client",
                client_secret_sealed=seal(CLIENT_SECRET, "google.client_secret"),
            )
        )
    locked = select(GoogleConnection).with_for_update(nowait=True)
    with Session(engine) as first, first.begin():
        assert first.scalar(locked) is not None
        # A second change waits for the first; with NOWAIT it is refused instead.
        with pytest.raises(OperationalError):
            with Session(engine) as second, second.begin():
                second.scalar(locked)
    with Session(engine) as session, session.begin():
        assert session.scalar(locked) is not None


# ---------- the routes, with the runtime role and a real table ----------

CLIENT_ID = "123456789012-synthetic0client.apps.googleusercontent.com"
OTHER_CLIENT_ID = "123456789012-another0client.apps.googleusercontent.com"
ENABLED = Settings(calendar_sync_enabled=True, token_key=KEY.token_key)


@pytest.fixture
def google_client(profile_client, local_session, monkeypatch):
    monkeypatch.setattr(google_connection, "get_settings", lambda: ENABLED)
    return profile_client


def row_of(engine):
    with Session(engine) as session:
        row = session.get(GoogleConnection, 1)
        if row is not None:
            session.expunge(row)
        return row


def test_saving_a_client_stores_the_secret_sealed_and_reports_no_secret(
    google_client, profile_database
):
    engine, _ = profile_database
    report = google_client.get("/api/google/connection").json()
    assert (report["state"], report["client_configured"]) == ("not_configured", False)

    response = google_client.put(
        "/api/google/client", json={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
    )
    assert response.status_code == 200 and CLIENT_SECRET not in response.text
    assert response.json() == google_client.get("/api/google/connection").json()
    assert response.json() == {
        "available": True,
        "unavailable_reason": None,
        "client_configured": True,
        "client_id": CLIENT_ID,
        "state": "not_connected",
        "granted_capabilities": [],
        "account_address": None,
    }
    row = row_of(engine)
    assert (row.client_id, row.state, row.key_version) == (CLIENT_ID, "not_connected", 1)
    assert row.refresh_token_sealed is None and CLIENT_SECRET not in row.client_secret_sealed
    opened = token_vault.open_sealed(
        row.client_secret_sealed, purpose=CLIENT_SECRET_PURPOSE, settings=ENABLED
    )
    assert opened == CLIENT_SECRET

    # Until an account is connected the client can be replaced, and there is still one row.
    response = google_client.put(
        "/api/google/client", json={"client_id": OTHER_CLIENT_ID, "client_secret": "another"}
    )
    assert response.status_code == 200 and response.json()["client_id"] == OTHER_CLIENT_ID
    replaced = row_of(engine)
    assert replaced.client_id == OTHER_CLIENT_ID and replaced.updated_at >= row.updated_at
    opened = token_vault.open_sealed(
        replaced.client_secret_sealed, purpose=CLIENT_SECRET_PURPOSE, settings=ENABLED
    )
    assert opened == "another"
    with Session(engine) as session:
        assert len(session.scalars(select(GoogleConnection)).all()) == 1


def test_a_connected_client_keeps_its_grant_and_cannot_be_swapped(google_client, profile_database):
    engine, _ = profile_database
    saved = google_client.put(
        "/api/google/client", json={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
    )
    assert saved.status_code == 200
    # A grant is placed directly; the consent flow that stores one is tested below.
    token = token_vault.seal(REFRESH_TOKEN, purpose=REFRESH_TOKEN_PURPOSE, settings=ENABLED)
    with Session(engine) as session, session.begin():
        row = session.get(GoogleConnection, 1, with_for_update=True)
        row.state, row.refresh_token_sealed, row.granted_scopes = "connected", token, [SCOPE]
    before = row_of(engine)

    refused = google_client.put(
        "/api/google/client", json={"client_id": OTHER_CLIENT_ID, "client_secret": "another"}
    )
    assert (refused.status_code, refused.json()) == (409, {"detail": CLIENT_IN_USE})
    unchanged = row_of(engine)
    assert (unchanged.client_id, unchanged.client_secret_sealed, unchanged.updated_at) == (
        before.client_id,
        before.client_secret_sealed,
        before.updated_at,
    )

    # A new secret for the same client replaces the secret and nothing else.
    rotated = google_client.put(
        "/api/google/client", json={"client_id": CLIENT_ID, "client_secret": "rotated-secret"}
    )
    assert rotated.status_code == 200 and rotated.json()["state"] == "connected"
    after = row_of(engine)
    assert (after.state, after.refresh_token_sealed, after.granted_scopes) == (
        "connected",
        token,
        [SCOPE],
    )
    opened = token_vault.open_sealed(
        after.client_secret_sealed, purpose=CLIENT_SECRET_PURPOSE, settings=ENABLED
    )
    assert opened == "rotated-secret"


def test_a_replaced_key_makes_the_stored_client_unreadable(
    google_client, profile_database, monkeypatch
):
    saved = google_client.put(
        "/api/google/client", json={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
    )
    assert saved.json()["state"] == "not_connected"
    replaced = Settings(
        calendar_sync_enabled=True,
        token_key=SecretStr("integration-test-only-replaced-key-0123456789ab"),
    )
    monkeypatch.setattr(google_connection, "get_settings", lambda: replaced)
    report = google_client.get("/api/google/connection").json()
    assert (report["state"], report["client_id"]) == ("unreadable", CLIENT_ID)
    # Saving the client again, with the key now in place, makes it readable.
    again = google_client.put(
        "/api/google/client", json={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
    )
    assert again.json()["state"] == "not_connected"


def test_nothing_is_stored_while_sync_is_switched_off(google_client, profile_database, monkeypatch):
    engine, _ = profile_database
    monkeypatch.setattr(google_connection, "get_settings", lambda: Settings())
    refused = google_client.put(
        "/api/google/client", json={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
    )
    assert refused.status_code == 409 and CLIENT_SECRET not in refused.text
    assert row_of(engine) is None


# ---------- the consent flow, with the runtime role, a real table and mocked Google ----------

BOTH_ON = Settings(gmail_sync_enabled=True, calendar_sync_enabled=True, token_key=KEY.token_key)
HOST = {"host": "127.0.0.1:15173"}
FIRST_ADDRESS = "first.synthetic.user@example.invalid"
SECOND_ADDRESS = "second.synthetic.user@example.invalid"


def token_response(refresh_token, scope):
    payload = {"access_token": "synthetic-access", "refresh_token": refresh_token, "scope": scope}
    return httpx.Response(200, json=payload)


@pytest.fixture
def consent(profile_client, local_session, monkeypatch):
    """The routes with both capabilities switched on, a fake flow store and mocked Google."""
    google = Google([])
    monkeypatch.setattr(google_connection, "get_settings", lambda: BOTH_ON)
    monkeypatch.setattr(google_consent, "get_settings", lambda: BOTH_ON)
    monkeypatch.setattr(
        google_consent,
        "_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(google.handler)),
    )
    redis = Redis()
    app.dependency_overrides[get_flow_store] = lambda: FlowStore(redis)
    saved = profile_client.put(
        "/api/google/client", json={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
    )
    assert saved.status_code == 200
    return profile_client, google


def connect(client, capabilities=("gmail", "calendar"), **callback):
    """Run one flow as a browser would, and return the callback's response."""
    started = client.post(
        "/api/google/connect",
        data={"capability": list(capabilities)},
        headers=HOST,
        follow_redirects=False,
    )
    assert started.status_code == 303
    state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
    params = {"state": state, "code": "synthetic-code", **callback}
    params = {name: value for name, value in params.items() if value is not None}
    return client.get(CALLBACK_PATH, params=params, headers=HOST, follow_redirects=False)


def opened_refresh_token(row):
    return token_vault.open_sealed(
        row.refresh_token_sealed, purpose=REFRESH_TOKEN_PURPOSE, settings=BOTH_ON
    )


def test_the_consent_flow_stores_a_sealed_grant(consent, profile_database):
    engine, _ = profile_database
    client, google = consent
    both = f"{gmail.SCOPE} {google_calendar.SCOPE}"
    google.token = token_response(REFRESH_TOKEN, both)
    google.profile = httpx.Response(200, json={"emailAddress": FIRST_ADDRESS})
    google.calendar = httpx.Response(200, json={"id": FIRST_ADDRESS})
    before = row_of(engine)

    finished = connect(client)
    assert (finished.status_code, finished.headers["location"]) == (303, "/?google=connected")
    assert google.sent(google_oauth.TOKEN_URL)[0]["client_secret"] == [CLIENT_SECRET]
    row = row_of(engine)
    assert (row.state, row.account_address, row.key_version) == ("connected", FIRST_ADDRESS, 1)
    assert row.granted_scopes == sorted([gmail.SCOPE, google_calendar.SCOPE])
    assert row.connected_at is not None and row.updated_at > before.updated_at
    assert REFRESH_TOKEN not in row.refresh_token_sealed
    assert opened_refresh_token(row) == REFRESH_TOKEN
    # The client saved before the flow is untouched.
    assert (row.client_id, row.client_secret_sealed) == (CLIENT_ID, before.client_secret_sealed)
    report = client.get("/api/google/connection").json()
    assert report == {
        "available": True,
        "unavailable_reason": None,
        "client_configured": True,
        "client_id": CLIENT_ID,
        "state": "connected",
        "granted_capabilities": ["gmail", "calendar"],
        "account_address": FIRST_ADDRESS,
    }
    with Session(engine) as session:
        assert len(session.scalars(select(GoogleConnection)).all()) == 1


def test_a_partial_grant_is_stored_and_reported_as_partial(consent, profile_database):
    engine, _ = profile_database
    client, google = consent
    google.token = token_response(REFRESH_TOKEN, google_calendar.SCOPE)
    google.calendar = httpx.Response(200, json={"id": FIRST_ADDRESS})
    finished = connect(client, ("gmail", "calendar"))
    assert finished.headers["location"] == "/?google=connected"
    assert row_of(engine).granted_scopes == [google_calendar.SCOPE]
    report = client.get("/api/google/connection").json()
    assert (report["state"], report["granted_capabilities"]) == ("connected", ["calendar"])


def test_another_account_replaces_the_grant_and_the_earlier_one_is_then_revoked(
    consent, profile_database
):
    engine, _ = profile_database
    client, google = consent
    google.token = token_response(REFRESH_TOKEN, gmail.SCOPE)
    google.profile = httpx.Response(200, json={"emailAddress": FIRST_ADDRESS})
    assert connect(client, ("gmail",)).headers["location"] == "/?google=connected"

    seen = []
    mocked = google.handler

    def handler(request):
        if str(request.url) == google_oauth.REVOCATION_URL:
            # By now the new grant is stored and the row lock has been given up, so the
            # lock is never held while Google is contacted.
            with Session(engine) as other, other.begin():
                locked = other.scalar(select(GoogleConnection).with_for_update(nowait=True))
                seen.append(locked.account_address)
        return mocked(request)

    google.handler = handler
    google.token = token_response("synthetic-second-refresh-token", gmail.SCOPE)
    google.profile = httpx.Response(200, json={"emailAddress": SECOND_ADDRESS})
    assert connect(client, ("gmail",)).headers["location"] == "/?google=connected"

    assert seen == [SECOND_ADDRESS]
    assert google.sent(google_oauth.REVOCATION_URL) == [{"token": [REFRESH_TOKEN]}]
    row = row_of(engine)
    assert (row.state, row.account_address) == ("connected", SECOND_ADDRESS)
    assert opened_refresh_token(row) == "synthetic-second-refresh-token"


def test_the_grant_is_written_under_the_row_lock(consent, profile_database, monkeypatch):
    """While the grant is being written, no other change can take the row."""
    engine, _ = profile_database
    client, google = consent
    google.token = token_response(REFRESH_TOKEN, gmail.SCOPE)
    google.profile = httpx.Response(200, json={"emailAddress": FIRST_ADDRESS})
    seen = []
    seal_value = token_vault.seal

    def sealing(value, **kwargs):
        # Called by the callback after it has locked the row and before it commits.
        if value == REFRESH_TOKEN:
            with pytest.raises(OperationalError):
                with Session(engine) as other, other.begin():
                    other.scalar(select(GoogleConnection).with_for_update(nowait=True))
            seen.append("locked")
        return seal_value(value, **kwargs)

    monkeypatch.setattr(token_vault, "seal", sealing)
    assert connect(client, ("gmail",)).headers["location"] == "/?google=connected"
    assert seen == ["locked"]
    with Session(engine) as session, session.begin():
        assert session.scalar(select(GoogleConnection).with_for_update(nowait=True)) is not None


def test_the_same_account_adding_a_capability_keeps_its_grant(consent, profile_database):
    engine, _ = profile_database
    client, google = consent
    google.token = token_response(REFRESH_TOKEN, google_calendar.SCOPE)
    google.calendar = httpx.Response(200, json={"id": FIRST_ADDRESS})
    assert connect(client, ("calendar",)).headers["location"] == "/?google=connected"

    # Gmail is added. The mailbox names the account differently from the calendar.
    both = f"{gmail.SCOPE} {google_calendar.SCOPE}"
    google.token = token_response("synthetic-second-refresh-token", both)
    google.profile = httpx.Response(200, json={"emailAddress": SECOND_ADDRESS})
    assert connect(client, ("gmail",)).headers["location"] == "/?google=connected"
    assert google.sent(google_oauth.REVOCATION_URL) == []
    row = row_of(engine)
    assert row.account_address == SECOND_ADDRESS
    assert row.granted_scopes == sorted([gmail.SCOPE, google_calendar.SCOPE])
    assert opened_refresh_token(row) == "synthetic-second-refresh-token"


def test_a_flow_that_does_not_complete_leaves_the_connection_as_it_was(consent, profile_database):
    engine, _ = profile_database
    client, google = consent
    google.token = token_response(REFRESH_TOKEN, gmail.SCOPE)
    google.profile = httpx.Response(200, json={"emailAddress": FIRST_ADDRESS})
    assert connect(client, ("gmail",)).headers["location"] == "/?google=connected"
    before = row_of(engine)

    def unchanged():
        row = row_of(engine)
        return (row.state, row.refresh_token_sealed, row.granted_scopes, row.updated_at) == (
            before.state,
            before.refresh_token_sealed,
            before.granted_scopes,
            before.updated_at,
        )

    declined = connect(client, ("gmail",), code=None, error="access_denied")
    assert declined.headers["location"] == "/?google=declined" and unchanged()

    google.token = httpx.Response(400, json={"error": "invalid_grant"})
    assert connect(client, ("gmail",)).headers["location"] == "/?google=failed" and unchanged()

    # Nothing asked for was granted. Revoking would end the stored grant, so nothing is.
    for scope in ("openid", gmail.SCOPE):
        google.token = token_response("synthetic-unused-refresh-token", scope)
        refused = connect(client, ("calendar",))
        assert refused.headers["location"] == "/?google=not_granted" and unchanged()
    assert google.sent(google_oauth.REVOCATION_URL) == []

    unknown = client.get(
        CALLBACK_PATH, params={"state": "A" * 43, "code": "synthetic-code"}, headers=HOST
    )
    assert (unknown.status_code, unknown.json()) == (400, {"detail": FLOW_REFUSED})
    assert unchanged()
