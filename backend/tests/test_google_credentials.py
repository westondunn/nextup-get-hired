"""Which Google credentials a sync uses, and the token step. No database, no network."""

from contextlib import contextmanager
from unittest.mock import MagicMock
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from test_gmail import FakeGmail, fake_session, message_payload
from test_google_calendar import FakeCalendar, event_payload
from test_google_calendar import fake_session as fake_calendar_session

from app import correspondence, google_credentials, token_vault
from app.config import Settings
from app.correspondence_tasks import sync_calendar, sync_gmail
from app.db import get_session
from app.google_connection import CLIENT_SECRET_PURPOSE, REFRESH_TOKEN_PURPOSE
from app.google_credentials import (
    NEEDS_REAUTHORIZATION,
    NOT_CONNECTED,
    UNREADABLE,
    access_token,
    not_granted,
    resolve,
    usable,
)
from app.main import app
from app.models import CorrespondenceSyncSettings, GoogleConnection
from app.sources import gmail, google_calendar
from app.sources.common import SourceError

KEY = "unit-test-only-token-key-0123456789abcdefghij"
CLIENT_ID = "123456789012-synthetic0client.apps.googleusercontent.com"
CLIENT_SECRET = "SYNTHETIC-stored-client-secret-that-must-never-leak"
REFRESH = "SYNTHETIC-stored-refresh-token-that-must-never-leak"
ISSUED = "SYNTHETIC-newly-issued-refresh-token-that-must-never-leak"
FALLBACK = dict(
    google_oauth_client_id=SecretStr("fallback-client"),
    google_oauth_client_secret=SecretStr("SYNTHETIC-fallback-secret-that-must-never-leak"),
    gmail_refresh_token=SecretStr("SYNTHETIC-fallback-token-that-must-never-leak"),
)
ON = dict(gmail_sync_enabled=True, calendar_sync_enabled=True)
# A key and both flags, and nothing in configuration to fall back to.
STORED_ONLY = Settings(**ON, token_key=SecretStr(KEY))
# The same with the complete fallback as well.
BOTH = Settings(**ON, token_key=SecretStr(KEY), **FALLBACK)
# The fallback alone, as an installation without a stored connection has it.
FALLBACK_ONLY = Settings(**ON, **FALLBACK)
SECRETS = (
    CLIENT_SECRET,
    REFRESH,
    ISSUED,
    FALLBACK["google_oauth_client_secret"].get_secret_value(),
    FALLBACK["gmail_refresh_token"].get_secret_value(),
)


def seal(value, purpose, settings=STORED_ONLY):
    return token_vault.seal(value, purpose=purpose, settings=settings)


def connection(**changes):
    values = dict(
        id=1,
        client_id=CLIENT_ID,
        client_secret_sealed=seal(CLIENT_SECRET, CLIENT_SECRET_PURPOSE),
        refresh_token_sealed=seal(REFRESH, REFRESH_TOKEN_PURPOSE),
        key_version=1,
        state="connected",
        granted_scopes=[gmail.SCOPE, google_calendar.SCOPE],
        account_address="person@example.test",
    )
    return GoogleConnection(**{**values, **changes})


def client_only():
    return connection(refresh_token_sealed=None, state="not_connected", granted_scopes=[])


def session_with(row):
    session = MagicMock()
    session.get.return_value = row
    return session


def refused(row, settings, capability="gmail"):
    with pytest.raises(SourceError) as caught:
        resolve(session_with(row), settings, capability)
    text = f"{caught.value.message} {caught.value!r} {caught.value.args}"
    assert not any(secret in text for secret in SECRETS)
    assert caught.value.__cause__ is None
    return caught.value.code, caught.value.message


# ---------- which credentials ----------


@pytest.mark.parametrize("capability", ["gmail", "calendar"])
def test_a_stored_connection_is_used_with_its_own_client(capability):
    row = connection()
    found = resolve(session_with(row), STORED_ONLY, capability)
    assert (found.client_id, found.client_secret, found.refresh_token) == (
        CLIENT_ID,
        CLIENT_SECRET,
        REFRESH,
    )
    assert found.stored_as == row.refresh_token_sealed


def test_a_stored_connection_takes_precedence_over_the_fallback():
    found = resolve(session_with(connection()), BOTH, "gmail")
    assert (found.client_id, found.refresh_token) == (CLIENT_ID, REFRESH)


@pytest.mark.parametrize("row", [None, client_only()])
def test_the_fallback_is_used_only_when_no_grant_is_stored(row):
    found = resolve(session_with(row), BOTH, "calendar")
    assert found.client_id == "fallback-client" and found.stored_as is None
    assert found.client_secret == FALLBACK["google_oauth_client_secret"].get_secret_value()
    assert found.refresh_token == FALLBACK["gmail_refresh_token"].get_secret_value()


@pytest.mark.parametrize("row", [None, client_only()])
def test_nothing_stored_and_no_fallback_is_not_connected(row):
    assert refused(row, STORED_ONLY) == ("not_connected", NOT_CONNECTED)


@pytest.mark.parametrize("missing", sorted(FALLBACK))
def test_an_incomplete_fallback_is_never_used(missing):
    partial = {name: value for name, value in FALLBACK.items() if name != missing}
    assert refused(None, Settings(**ON, **partial)) == ("not_connected", NOT_CONNECTED)


@pytest.mark.parametrize("settings", [STORED_ONLY, BOTH])
def test_a_connection_that_needs_reauthorization_stops_sync_and_is_not_replaced(settings):
    row = connection(state="needs_reauthorization")
    for capability in ("gmail", "calendar"):
        assert refused(row, settings, capability) == (
            "needs_reauthorization",
            NEEDS_REAUTHORIZATION,
        )


@pytest.mark.parametrize("settings", [STORED_ONLY, BOTH])
@pytest.mark.parametrize(
    "granted,without,other",
    [
        ([gmail.SCOPE], "calendar", "gmail"),
        ([google_calendar.SCOPE, "openid"], "gmail", "calendar"),
        (["https://www.googleapis.com/auth/gmail.modify", google_calendar.SCOPE], "gmail", None),
    ],
)
def test_a_grant_without_the_scope_stops_that_capability_only(settings, granted, without, other):
    row = connection(granted_scopes=granted)
    assert refused(row, settings, without) == ("capability_not_granted", not_granted(without))
    if other:
        assert resolve(session_with(row), settings, other).refresh_token == REFRESH


def test_every_reason_fits_the_stored_status_column():
    codes = ("not_connected", "needs_reauthorization", "capability_not_granted")
    for code in (*codes, "connection_unreadable", "connection_not_updated"):
        assert len(code) <= CorrespondenceSyncSettings.last_status.type.length == 30


def test_the_refusal_names_the_capability():
    assert "Gmail access" in not_granted("gmail") and "Calendar access" in not_granted("calendar")


OTHER_KEY = Settings(**ON, token_key=SecretStr("another-unit-test-only-token-key-0123456789"))


@pytest.mark.parametrize(
    "row,settings",
    [
        (connection(), OTHER_KEY),
        (connection(), Settings(**ON)),  # the key file is missing
        (connection(), Settings(**ON, **FALLBACK)),  # missing, and the fallback is complete
        (connection(refresh_token_sealed=seal(REFRESH, CLIENT_SECRET_PURPOSE)), STORED_ONLY),
        (connection(client_secret_sealed=seal(CLIENT_SECRET, REFRESH_TOKEN_PURPOSE)), BOTH),
        (connection(refresh_token_sealed="v1.not-a-sealed-value"), STORED_ONLY),
    ],
)
def test_a_connection_the_key_cannot_open_is_unreadable_and_is_not_replaced(row, settings):
    assert refused(row, settings) == ("connection_unreadable", UNREADABLE)


@pytest.mark.parametrize("row", [None, connection()])
def test_nothing_is_read_or_opened_in_fixture_data_mode(row, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a credential was opened in fixture data mode")

    monkeypatch.setattr(token_vault, "open_sealed", refuse)
    session = session_with(row)
    with pytest.raises(SourceError) as caught:
        resolve(session, BOTH.model_copy(update={"fixture_data_mode": True}), "gmail")
    assert caught.value.code == "fixture_mode"
    session.get.assert_not_called()


def test_credentials_cannot_be_printed():
    found = resolve(session_with(connection()), STORED_ONLY, "gmail")
    assert not any(secret in f"{found!r} {found}" for secret in SECRETS)


def test_usable_says_whether_a_sync_would_have_credentials():
    assert usable(session_with(connection()), STORED_ONLY, "gmail") is True
    assert usable(session_with(None), FALLBACK_ONLY, "calendar") is True
    assert usable(session_with(None), STORED_ONLY, "gmail") is False
    assert usable(session_with(connection(granted_scopes=[gmail.SCOPE])), BOTH, "calendar") is False
    in_fixture_mode = BOTH.model_copy(update={"fixture_data_mode": True})
    assert usable(session_with(connection()), in_fixture_mode, "gmail") is False


def test_reading_the_connection_takes_no_lock():
    session = session_with(connection())
    resolve(session, STORED_ONLY, "gmail")
    session.get.assert_called_once_with(GoogleConnection, 1)
    assert not session.commit.called and not session.add.called


# ---------- the token step ----------

BOTH_SCOPES = f"{gmail.SCOPE} {google_calendar.SCOPE}"


class Tokens:
    def __init__(self, response=None, **extra):
        self.requests = []
        self.response = response or httpx.Response(
            200, json={"access_token": "synthetic-access", "scope": BOTH_SCOPES, **extra}
        )

    def handler(self, request):
        self.requests.append(request)
        return self.response

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


class ShortSession:
    """Stands in for the separate session that stores a newly issued refresh token."""

    def __init__(self, row):
        self.row = row
        self.events = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.events.append("closed")

    @contextmanager
    def begin(self):
        self.events.append("begin")
        yield
        self.events.append("commit")

    def get(self, model, key, **kwargs):
        assert (model, key) == (GoogleConnection, 1)
        self.events.append(kwargs)
        return self.row


@pytest.fixture
def short(monkeypatch):
    holder = ShortSession(connection())
    monkeypatch.setattr(google_credentials, "_connection_session", lambda session: holder)
    return holder


def stored_credentials(row):
    return resolve(session_with(row), STORED_ONLY, "gmail")


def opened(row):
    return token_vault.open_sealed(
        row.refresh_token_sealed, purpose=REFRESH_TOKEN_PURPOSE, settings=STORED_ONLY
    )


@pytest.mark.parametrize("capability", ["gmail", "calendar"])
def test_the_refresh_request_carries_the_resolved_credentials_once(capability, short):
    tokens = Tokens()
    credentials = stored_credentials(short.row)
    with tokens.client() as client:
        token = access_token(client, MagicMock(), STORED_ONLY, credentials, capability)
    assert token == "synthetic-access"
    (request,) = tokens.requests
    assert (request.method, str(request.url)) == ("POST", gmail.TOKEN_URL)
    assert parse_qs(request.content.decode(), strict_parsing=True) == {
        "client_id": [CLIENT_ID],
        "client_secret": [CLIENT_SECRET],
        "refresh_token": [REFRESH],
        "grant_type": ["refresh_token"],
    }
    assert short.events == []  # nothing was issued, so the connection is not touched


@pytest.mark.parametrize(
    "capability,scope",
    [("gmail", google_calendar.SCOPE), ("calendar", gmail.SCOPE), ("calendar", "")],
)
def test_a_token_without_the_capability_scope_is_refused(capability, scope, short):
    tokens = Tokens(httpx.Response(200, json={"access_token": "synthetic-access", "scope": scope}))
    with tokens.client() as client, pytest.raises(SourceError) as caught:
        access_token(client, MagicMock(), STORED_ONLY, stored_credentials(short.row), capability)
    assert caught.value.code == "wrong_scope"


@pytest.mark.parametrize(
    "response,code",
    [
        (httpx.Response(400, json={"error": "invalid_grant"}), "provider_rejected"),
        (httpx.Response(401), "unauthorized"),
        (httpx.Response(503), "provider_unavailable"),
        (httpx.Response(200, json={"scope": BOTH_SCOPES}), "unauthorized"),
    ],
)
def test_a_refused_refresh_is_reported_and_not_retried(response, code, short):
    tokens = Tokens(response)
    with tokens.client() as client, pytest.raises(SourceError) as caught:
        access_token(client, MagicMock(), STORED_ONLY, stored_credentials(short.row), "gmail")
    assert caught.value.code == code and len(tokens.requests) == 1
    assert short.events == [] and opened(short.row) == REFRESH


def test_no_request_is_made_in_fixture_data_mode(short):
    tokens = Tokens()
    settings = STORED_ONLY.model_copy(update={"fixture_data_mode": True})
    with tokens.client() as client, pytest.raises(SourceError) as caught:
        access_token(client, MagicMock(), settings, stored_credentials(short.row), "gmail")
    assert caught.value.code == "fixture_mode" and tokens.requests == []


def test_a_newly_issued_refresh_token_replaces_the_stored_one_under_the_row_lock(short):
    tokens = Tokens(refresh_token=ISSUED)
    main = MagicMock()
    with tokens.client() as client:
        token = access_token(client, main, STORED_ONLY, stored_credentials(short.row), "gmail")
    assert token == "synthetic-access"
    assert short.events == [
        "begin",
        {"with_for_update": True, "populate_existing": True},
        "commit",
        "closed",
    ]
    assert ISSUED not in short.row.refresh_token_sealed and opened(short.row) == ISSUED
    assert short.row.key_version == 1 and short.row.updated_at is not None
    # The sync's own session is not used for the change and is not committed by it.
    assert not main.commit.called and not main.get.called


def test_the_new_token_is_kept_even_when_the_scope_check_then_fails(short):
    tokens = Tokens(
        httpx.Response(
            200,
            json={
                "access_token": "synthetic-access",
                "scope": google_calendar.SCOPE,
                "refresh_token": ISSUED,
            },
        )
    )
    with tokens.client() as client, pytest.raises(SourceError):
        access_token(client, MagicMock(), STORED_ONLY, stored_credentials(short.row), "gmail")
    assert opened(short.row) == ISSUED


@pytest.mark.parametrize("issued", [REFRESH, "", "has space", 7, None, "x" * 5000])
def test_a_repeated_or_unusable_refresh_token_changes_nothing(issued, short):
    tokens = Tokens(refresh_token=issued)
    with tokens.client() as client:
        access_token(client, MagicMock(), STORED_ONLY, stored_credentials(short.row), "gmail")
    assert short.events == [] and opened(short.row) == REFRESH


def test_a_connection_replaced_in_the_meantime_is_left_alone(short):
    credentials = stored_credentials(short.row)
    # Another flow stored a different grant after these credentials were read.
    short.row.refresh_token_sealed = seal("a-different-grant", REFRESH_TOKEN_PURPOSE)
    tokens = Tokens(refresh_token=ISSUED)
    with tokens.client() as client:
        access_token(client, MagicMock(), STORED_ONLY, credentials, "gmail")
    assert opened(short.row) == "a-different-grant"
    assert short.events[-2:] == ["commit", "closed"]  # the lock was taken and given up


def test_a_connection_removed_in_the_meantime_is_left_alone(short):
    credentials = stored_credentials(short.row)
    short.row = None
    tokens = Tokens(refresh_token=ISSUED)
    with tokens.client() as client:
        assert access_token(client, MagicMock(), STORED_ONLY, credentials, "gmail")


def test_a_new_token_that_cannot_be_stored_stops_the_sync_with_a_fixed_reason(short):
    from sqlalchemy.exc import OperationalError

    def locked(model, key, **kwargs):
        raise OperationalError("SELECT naming " + REFRESH, {}, Exception("lock timeout"))

    short.get = locked
    tokens = Tokens(refresh_token=ISSUED)
    with tokens.client() as client, pytest.raises(SourceError) as caught:
        access_token(client, MagicMock(), STORED_ONLY, stored_credentials(short.row), "gmail")
    assert (caught.value.code, caught.value.message) == (
        "connection_not_updated",
        google_credentials.NOT_UPDATED,
    )
    assert caught.value.__cause__ is None and len(caught.value.code) <= 30


def test_a_token_issued_to_the_fallback_is_not_stored(short):
    tokens = Tokens(refresh_token=ISSUED)
    credentials = resolve(session_with(None), FALLBACK_ONLY, "gmail")
    with tokens.client() as client:
        access_token(client, MagicMock(), FALLBACK_ONLY, credentials, "gmail")
    assert short.events == [] and opened(short.row) == REFRESH


# ---------- both syncs ----------


def mail_config():
    return CorrespondenceSyncSettings(id=1, enabled=True, query="label:x", max_messages_per_run=5)


def calendar_config():
    return CorrespondenceSyncSettings(id=1, calendar_enabled=True, calendar_lookahead_days=14)


def token_request(fake):
    (request,) = [r for r in fake.requests if r.url.host == "oauth2.googleapis.com"]
    return parse_qs(request.content.decode(), strict_parsing=True)


@pytest.mark.parametrize("settings", [STORED_ONLY, BOTH])
def test_mail_sync_uses_the_stored_connection(settings):
    fake = FakeGmail([message_payload("m1", "a@example.test", "Hello", "Body", 1_700_000_000_000)])
    config = mail_config()
    session = fake_session(config, connection=connection())
    with fake.client() as client:
        result = sync_gmail(session, settings, client=client)
    assert (result["status"], result["imported"]) == ("ok", 1)
    assert token_request(fake)["client_secret"] == [CLIENT_SECRET]
    assert token_request(fake)["refresh_token"] == [REFRESH]


@pytest.mark.parametrize("settings", [STORED_ONLY, BOTH])
def test_calendar_sync_uses_the_stored_connection(settings):
    fake = FakeCalendar([event_payload("e1", "Interview", "2026-11-20T15:00:00Z")])
    config = calendar_config()
    session = fake_calendar_session(config, connection=connection())
    with fake.client() as client:
        result = sync_calendar(session, settings, client=client)
    assert (result["status"], result["imported"]) == ("ok", 1)
    assert token_request(fake)["client_id"] == [CLIENT_ID]
    assert token_request(fake)["refresh_token"] == [REFRESH]


def no_client(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("an HTTP client was constructed")

    monkeypatch.setattr(httpx, "Client", refuse)


@pytest.mark.parametrize(
    "row,settings,code",
    [
        (None, STORED_ONLY, "not_connected"),
        (client_only(), STORED_ONLY, "not_connected"),
        (connection(state="needs_reauthorization"), BOTH, "needs_reauthorization"),
        (connection(granted_scopes=["openid"]), BOTH, "capability_not_granted"),
        (connection(), OTHER_KEY, "connection_unreadable"),
    ],
)
def test_a_sync_without_usable_credentials_records_why_and_contacts_nothing(
    row, settings, code, monkeypatch
):
    no_client(monkeypatch)  # the sync is called without a client and must not make one
    config = mail_config()
    session = fake_session(config, connection=row)
    result = sync_gmail(session, settings)
    assert (result["status"], result["imported"]) == (code, 0)
    assert config.last_status == code and config.last_error == result["error"]
    assert not any(secret in config.last_error for secret in SECRETS)
    assert session.added == []

    config = calendar_config()
    session = fake_calendar_session(config, connection=row)
    result = sync_calendar(session, settings)
    assert (result["status"], result["imported"]) == (code, 0)
    assert config.calendar_last_status == code and session.added == []


def test_a_capability_that_was_not_granted_does_not_stop_the_other(monkeypatch):
    row = connection(granted_scopes=[google_calendar.SCOPE])
    mail = mail_config()
    assert sync_gmail(fake_session(mail, connection=row), STORED_ONLY)["status"] == (
        "capability_not_granted"
    )
    assert "Gmail access" in mail.last_error
    fake = FakeCalendar([event_payload("e1", "Interview", "2026-11-20T15:00:00Z")])
    with fake.client() as client:
        result = sync_calendar(
            fake_calendar_session(calendar_config(), connection=row), STORED_ONLY, client=client
        )
    assert result["status"] == "ok"


def test_a_switched_off_sync_is_reported_as_before_and_reads_no_connection():
    config = mail_config()
    session = fake_session(config, connection=connection())
    assert sync_gmail(session, Settings(token_key=SecretStr(KEY)))["status"] == "not_configured"
    assert [call.args[0] for call in session.get.call_args_list] == [CorrespondenceSyncSettings]


# ---------- turning sync on in Settings ----------


@pytest.fixture
def settings_api(local_session, monkeypatch):
    database = MagicMock()
    rows = {CorrespondenceSyncSettings: None, GoogleConnection: None}
    database.get.side_effect = lambda model, *args, **kwargs: rows[model]
    database.scalar.return_value = 0
    current = {"settings": STORED_ONLY}
    monkeypatch.setattr(correspondence, "get_settings", lambda: current["settings"])
    app.dependency_overrides[get_session] = lambda: database
    try:
        yield TestClient(app), database, rows, current
    finally:
        app.dependency_overrides.pop(get_session, None)


MAIL_ON = {"enabled": True, "query": "label:job-search", "max_messages_per_run": 25}
CALENDAR_ON = {**MAIL_ON, "enabled": False, "calendar_enabled": True}


def test_the_report_says_which_capabilities_have_credentials(settings_api):
    client, _, rows, current = settings_api
    body = client.get("/api/correspondence").json()
    assert (body["credentials_present"], body["calendar_credentials_present"]) == (False, False)
    rows[GoogleConnection] = connection(granted_scopes=[google_calendar.SCOPE])
    body = client.get("/api/correspondence").json()
    assert (body["credentials_present"], body["calendar_credentials_present"]) == (False, True)
    rows[GoogleConnection] = None
    current["settings"] = FALLBACK_ONLY
    body = client.get("/api/correspondence").json()
    assert (body["credentials_present"], body["calendar_credentials_present"]) == (True, True)


@pytest.mark.parametrize(
    "body,message",
    [
        (MAIL_ON, correspondence.GMAIL_NOT_CONNECTED),
        (CALENDAR_ON, correspondence.CALENDAR_NOT_CONNECTED),
    ],
)
def test_sync_cannot_be_turned_on_without_credentials_it_could_use(settings_api, body, message):
    client, database, rows, _ = settings_api
    for row in (None, client_only(), connection(granted_scopes=["openid"])):
        rows[GoogleConnection] = row
        response = client.put("/api/correspondence", json=body)
        assert (response.status_code, response.json()) == (409, {"detail": message})
    database.commit.assert_not_called()


@pytest.mark.parametrize(
    "body,settings,message",
    [
        (MAIL_ON, Settings(calendar_sync_enabled=True), correspondence.GMAIL_SWITCHED_OFF),
        (CALENDAR_ON, Settings(gmail_sync_enabled=True), correspondence.CALENDAR_SWITCHED_OFF),
    ],
)
def test_the_configuration_flag_is_still_the_outer_switch(settings_api, body, settings, message):
    client, database, rows, current = settings_api
    rows[GoogleConnection] = connection()
    current["settings"] = settings.model_copy(update={"token_key": SecretStr(KEY)})
    response = client.put("/api/correspondence", json=body)
    assert (response.status_code, response.json()) == (409, {"detail": message})
    database.commit.assert_not_called()


@pytest.mark.parametrize(
    "body,granted,allowed",
    [
        (MAIL_ON, [gmail.SCOPE], True),
        (MAIL_ON, [google_calendar.SCOPE], False),
        (CALENDAR_ON, [google_calendar.SCOPE], True),
        (CALENDAR_ON, [gmail.SCOPE], False),
    ],
)
def test_a_stored_connection_allows_only_the_capabilities_it_grants(
    settings_api, body, granted, allowed
):
    client, database, rows, _ = settings_api
    rows[GoogleConnection] = connection(granted_scopes=granted)
    rows[CorrespondenceSyncSettings] = CorrespondenceSyncSettings(
        id=1,
        enabled=False,
        query="label:job-search",
        max_messages_per_run=25,
        calendar_enabled=False,
        calendar_lookahead_days=14,
        auto_create_applications=False,
        last_status="not_run",
        last_error="",
        last_imported=0,
        calendar_last_status="not_run",
        calendar_last_error="",
        calendar_last_imported=0,
    )
    response = client.put("/api/correspondence", json=body)
    assert response.status_code == (200 if allowed else 409)
    assert database.commit.called is allowed
    if allowed:
        saved = response.json()
        assert saved["enabled"] is body["enabled"]
        assert saved["calendar_enabled"] is body.get("calendar_enabled", False)
