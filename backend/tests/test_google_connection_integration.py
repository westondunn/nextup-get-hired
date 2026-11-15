"""The stored Google connection, written and read by the runtime role through the model."""

import os

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from test_profile_integration import profile_database as profile_database

from app import token_vault
from app.config import Settings
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
