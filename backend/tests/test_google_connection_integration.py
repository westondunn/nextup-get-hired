"""The stored Google connection, written and read by the runtime role.

First through the model, then through the routes that save and report the user's client.
"""

import os

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from test_profile_integration import profile_client as profile_client
from test_profile_integration import profile_database as profile_database

from app import google_connection, token_vault
from app.config import Settings
from app.google_connection import CLIENT_IN_USE, CLIENT_SECRET_PURPOSE, REFRESH_TOKEN_PURPOSE
from app.models import GoogleConnection

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
    # No route stores a grant yet, so one is placed here as the consent flow will.
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
