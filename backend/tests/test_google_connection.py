"""Saving and reporting the user's Google OAuth client. No database and no network."""

import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import google_connection, token_vault
from app.config import Settings
from app.db import get_session
from app.google_connection import (
    CLIENT_IN_USE,
    CLIENT_SECRET_PURPOSE,
    FIXTURE_MODE,
    INVALID_CLIENT_ID,
    INVALID_CLIENT_SECRET,
    INVALID_REQUEST,
    NO_KEY,
    REFRESH_TOKEN_PURPOSE,
    SWITCHED_OFF,
)
from app.main import app
from app.models import GoogleConnection

pytestmark = pytest.mark.usefixtures("local_session")

KEY = "unit-test-only-token-key-0123456789abcdefghij"
CLIENT_ID = "123456789012-synthetic0client.apps.googleusercontent.com"
OTHER_CLIENT_ID = "123456789012-another0client.apps.googleusercontent.com"
CLIENT_SECRET = "SYNTHETIC-client-secret-that-must-never-leak"
REFRESH_TOKEN = "synthetic-refresh-token-that-must-never-leak"
ENABLED = Settings(gmail_sync_enabled=True, token_key=SecretStr(KEY))
BODY = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}


def seal(value, purpose, settings=ENABLED):
    return token_vault.seal(value, purpose=purpose, settings=settings)


def stored(**changes):
    values = dict(
        id=1,
        client_id=CLIENT_ID,
        client_secret_sealed=seal("an-earlier-secret", CLIENT_SECRET_PURPOSE),
        refresh_token_sealed=None,
        key_version=1,
        state="not_connected",
        granted_scopes=[],
    )
    return GoogleConnection(**{**values, **changes})


def connected(**changes):
    values = dict(
        state="connected", refresh_token_sealed=seal(REFRESH_TOKEN, REFRESH_TOKEN_PURPOSE)
    )
    return stored(**{**values, **changes})


@pytest.fixture
def api(monkeypatch):
    """The real application, a database double, and settings that allow a connection."""
    database = MagicMock()
    database.get.return_value = None
    current = {"settings": ENABLED}
    monkeypatch.setattr(google_connection, "get_settings", lambda: current["settings"])
    app.dependency_overrides[get_session] = lambda: database
    try:
        yield TestClient(app), database, current
    finally:
        app.dependency_overrides.pop(get_session, None)


def leaks(response):
    return CLIENT_SECRET in response.text or REFRESH_TOKEN in response.text


# ---------- refusals that come before anything is stored ----------


@pytest.mark.parametrize(
    "settings,status,message",
    [
        (Settings(token_key=SecretStr(KEY)), 409, SWITCHED_OFF),
        (Settings(gmail_sync_enabled=True), 503, NO_KEY),
        (Settings(calendar_sync_enabled=True, token_key=SecretStr("short")), 503, NO_KEY),
        (Settings(fixture_data_mode=True, token_key=SecretStr(KEY)), 409, FIXTURE_MODE),
        # Fixture data mode is checked first, whatever else is set.
        (
            Settings(fixture_data_mode=True, gmail_sync_enabled=True, token_key=SecretStr(KEY)),
            409,
            FIXTURE_MODE,
        ),
    ],
)
def test_no_client_is_saved_where_a_connection_is_not_available(api, settings, status, message):
    client, database, current = api
    current["settings"] = settings
    response = client.put("/api/google/client", json=BODY)
    assert (response.status_code, response.json()) == (status, {"detail": message})
    assert not database.method_calls and not leaks(response)


def test_either_sync_flag_makes_a_connection_available(api):
    client, _, current = api
    for flag in ("gmail_sync_enabled", "calendar_sync_enabled"):
        current["settings"] = Settings(**{flag: True}, token_key=SecretStr(KEY))
        assert client.get("/api/google/connection").json()["available"] is True


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        b"[]",
        b'"text"',
        b"{}",
        json.dumps({"client_id": CLIENT_ID}).encode(),
        json.dumps({**BODY, "extra": CLIENT_SECRET}).encode(),
        json.dumps({"client_id": 1, "client_secret": CLIENT_SECRET}).encode(),
        json.dumps({"client_id": CLIENT_ID, "client_secret": [CLIENT_SECRET]}).encode(),
        json.dumps({**BODY, "client_secret": CLIENT_SECRET + "x" * 5000}).encode(),
        b"\xff\xfe" + CLIENT_SECRET.encode(),
        b"[" * 3000,
    ],
)
def test_a_malformed_request_is_refused_without_repeating_it(api, body):
    client, database, _ = api
    response = client.put(
        "/api/google/client", content=body, headers={"Content-Type": "application/json"}
    )
    assert (response.status_code, response.json()) == (422, {"detail": INVALID_REQUEST})
    assert not database.method_calls and not leaks(response)


@pytest.mark.parametrize(
    "client_id",
    [
        "",
        "synthetic-client",
        # A secret pasted into the wrong field must not be stored as a plain client ID.
        CLIENT_SECRET,
        "apps.googleusercontent.com",
        ".apps.googleusercontent.com",
        CLIENT_ID + " ",
        CLIENT_ID + "\n",
        "https://" + CLIENT_ID,
        CLIENT_ID + ".example.invalid",
        "x" * 300 + ".apps.googleusercontent.com",
    ],
)
def test_a_client_id_in_another_form_is_refused(api, client_id):
    client, database, _ = api
    response = client.put(
        "/api/google/client", json={"client_id": client_id, "client_secret": CLIENT_SECRET}
    )
    assert (response.status_code, response.json()) == (422, {"detail": INVALID_CLIENT_ID})
    assert not database.method_calls and not leaks(response)


@pytest.mark.parametrize("secret", ["", "has a space", "line\nbreak", "tab\there", "x" * 513])
def test_an_unusable_client_secret_is_refused(api, secret):
    client, database, _ = api
    response = client.put(
        "/api/google/client", json={"client_id": CLIENT_ID, "client_secret": secret}
    )
    assert (response.status_code, response.json()) == (422, {"detail": INVALID_CLIENT_SECRET})
    assert not database.method_calls and (not secret or secret not in response.text)


# ---------- saving ----------


def test_the_secret_is_sealed_before_it_reaches_the_database(api):
    client, database, _ = api
    database.get.return_value = stored(client_id=OTHER_CLIENT_ID)
    response = client.put("/api/google/client", json=BODY)
    assert response.status_code == 200 and not leaks(response)
    assert response.json() == {
        "available": True,
        "unavailable_reason": None,
        "client_configured": True,
        "client_id": CLIENT_ID,
        "state": "not_connected",
        "granted_capabilities": [],
        "account_address": None,
    }
    # The statement that creates the row carries the sealed value and never the plain one.
    (statement,) = database.execute.call_args.args
    parameters = statement.compile().params
    assert parameters["client_id"] == CLIENT_ID and parameters["key_version"] == 1
    assert CLIENT_SECRET not in json.dumps(parameters)
    opened = token_vault.open_sealed(
        parameters["client_secret_sealed"], purpose=CLIENT_SECRET_PURPOSE, settings=ENABLED
    )
    assert opened == CLIENT_SECRET
    # The existing row is read under the row lock and replaced with the same sealed value.
    assert database.get.call_args.kwargs == {"with_for_update": True}
    row = database.get.return_value
    assert (row.client_id, row.client_secret_sealed) == (
        CLIENT_ID,
        parameters["client_secret_sealed"],
    )
    database.commit.assert_called_once()


def test_a_different_client_is_refused_while_an_account_is_connected(api):
    client, database, _ = api
    for state in ("connected", "needs_reauthorization"):
        row = connected(state=state, client_id=OTHER_CLIENT_ID)
        before = (row.client_id, row.client_secret_sealed, row.refresh_token_sealed)
        database.reset_mock()
        database.get.return_value = row
        response = client.put("/api/google/client", json=BODY)
        assert (response.status_code, response.json()) == (409, {"detail": CLIENT_IN_USE})
        assert (row.client_id, row.client_secret_sealed, row.refresh_token_sealed) == before
        database.rollback.assert_called_once()
        database.commit.assert_not_called()


def test_a_new_secret_for_the_connected_client_keeps_the_grant(api):
    client, database, _ = api
    row = connected()
    token = row.refresh_token_sealed
    database.get.return_value = row
    response = client.put("/api/google/client", json=BODY)
    assert response.status_code == 200 and response.json()["state"] == "connected"
    assert (row.state, row.refresh_token_sealed) == ("connected", token)
    opened = token_vault.open_sealed(
        row.client_secret_sealed, purpose=CLIENT_SECRET_PURPOSE, settings=ENABLED
    )
    assert opened == CLIENT_SECRET


# ---------- reporting ----------


def test_nothing_stored_is_reported_as_not_configured(api):
    client, _, current = api
    assert client.get("/api/google/connection").json() == {
        "available": True,
        "unavailable_reason": None,
        "client_configured": False,
        "client_id": None,
        "state": "not_configured",
        "granted_capabilities": [],
        "account_address": None,
    }
    current["settings"] = Settings()
    assert client.get("/api/google/connection").json() == {
        "available": False,
        "unavailable_reason": "switched_off",
        "client_configured": False,
        "client_id": None,
        "state": "not_configured",
        "granted_capabilities": [],
        "account_address": None,
    }


@pytest.mark.parametrize(
    "settings,reason",
    [
        (Settings(fixture_data_mode=True), "fixture_mode"),
        (Settings(), "switched_off"),
        (Settings(gmail_sync_enabled=True), "no_key"),
    ],
)
def test_the_report_says_why_a_connection_is_not_available(api, settings, reason):
    client, _, current = api
    current["settings"] = settings
    body = client.get("/api/google/connection").json()
    assert (body["available"], body["unavailable_reason"]) == (False, reason)


def test_the_report_carries_the_state_and_never_a_credential(api):
    client, database, _ = api
    for row in (stored(), connected(), connected(state="needs_reauthorization")):
        database.get.return_value = row
        response = client.get("/api/google/connection")
        assert response.json()["state"] == row.state
        assert response.json()["client_id"] == CLIENT_ID
        assert set(response.json()) == {
            "available",
            "unavailable_reason",
            "client_configured",
            "client_id",
            "state",
            "granted_capabilities",
            "account_address",
        }
        assert row.client_secret_sealed not in response.text and not leaks(response)
        assert row.refresh_token_sealed is None or row.refresh_token_sealed not in response.text


def test_the_report_names_what_google_granted_and_the_connected_account(api):
    client, database, _ = api
    gmail = "https://www.googleapis.com/auth/gmail.readonly"
    calendar = "https://www.googleapis.com/auth/calendar.readonly"
    cases = [
        ([], []),
        ([gmail], ["gmail"]),
        ([calendar], ["calendar"]),
        ([calendar, gmail, "openid"], ["gmail", "calendar"]),
        # A wider scope is not the read-only capability, and never counts as it.
        (["https://www.googleapis.com/auth/gmail.modify"], []),
    ]
    for scopes, capabilities in cases:
        database.get.return_value = connected(
            granted_scopes=scopes, account_address="person@example.test"
        )
        body = client.get("/api/google/connection").json()
        assert body["granted_capabilities"] == capabilities
        assert body["account_address"] == "person@example.test"


def test_a_record_the_key_cannot_open_is_reported_as_unreadable(api):
    client, database, current = api
    other = Settings(gmail_sync_enabled=True, token_key=SecretStr("another-" + KEY))
    cases = [
        (stored(), other),
        (connected(), other),
        # The key file is missing.
        (connected(), Settings(gmail_sync_enabled=True)),
        # A value sealed for one field does not open as the other.
        (
            connected(refresh_token_sealed=seal(REFRESH_TOKEN, CLIENT_SECRET_PURPOSE)),
            ENABLED,
        ),
    ]
    for row, settings in cases:
        database.get.return_value = row
        current["settings"] = settings
        body = client.get("/api/google/connection").json()
        assert (body["state"], body["client_configured"]) == ("unreadable", True)


def test_nothing_in_the_module_logs():
    source = open(google_connection.__file__).read()
    assert "logging" not in source and "print(" not in source
