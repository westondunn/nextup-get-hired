"""The Google consent flow: start route, callback and access log. No database, no network."""

import json
import logging
import threading
import time
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from pydantic import SecretStr
from redis.exceptions import ConnectionError as RedisConnectionError
from test_local_session import FakeRedis

from app import google_consent, token_vault
from app.config import Settings
from app.db import get_session
from app.google_connection import (
    CLIENT_SECRET_PURPOSE,
    FIXTURE_MODE,
    NO_KEY,
    REFRESH_TOKEN_PURPOSE,
    SWITCHED_OFF,
)
from app.google_consent import (
    BINDING_COOKIE_PREFIX,
    CALLBACK_PATH,
    CAPABILITY_OFF,
    CLIENT_UNREADABLE,
    FLOW_KEY_PREFIX,
    FLOW_REFUSED,
    FLOW_SECONDS,
    HOST_NOT_LOCAL,
    INVALID_CAPABILITIES,
    NO_CLIENT,
    RESULT_ADDRESS,
    RESULTS,
    CallbackQueryFilter,
    FlowStore,
    get_flow_store,
)
from app.local_session import STORE_UNAVAILABLE, SessionStore, get_store, require_session
from app.main import app
from app.models import GoogleConnection
from app.sources import gmail, google_calendar, google_oauth

pytestmark = pytest.mark.usefixtures("local_session")

KEY = "unit-test-only-token-key-0123456789abcdefghij"
CLIENT_ID = "123456789012-synthetic0client.apps.googleusercontent.com"
CLIENT_SECRET = "SYNTHETIC-client-secret-that-must-never-leak"
CODE = "4/SYNTHETIC-authorization-code-that-must-never-leak"
ACCESS = "SYNTHETIC-access-token-that-must-never-leak"
REFRESH = "SYNTHETIC-refresh-token-that-must-never-leak"
EARLIER_REFRESH = "SYNTHETIC-earlier-refresh-token-that-must-never-leak"
ADDRESS = "person@example.test"
BOTH = f"{gmail.SCOPE} {google_calendar.SCOPE}"
ENABLED = Settings(gmail_sync_enabled=True, calendar_sync_enabled=True, token_key=SecretStr(KEY))
HOST = "127.0.0.1:15173"
START = "/api/google/connect"


class Redis(FakeRedis):
    """The fake store of the session tests, with the one further command the flow uses."""

    def getdel(self, key):
        value = self.get(key)
        self.data.pop(key, None)
        return value


def seal(value, purpose, settings=ENABLED):
    return token_vault.seal(value, purpose=purpose, settings=settings)


def stored(**changes):
    values = dict(
        id=1,
        client_id=CLIENT_ID,
        client_secret_sealed=seal(CLIENT_SECRET, CLIENT_SECRET_PURPOSE),
        refresh_token_sealed=None,
        key_version=1,
        state="not_connected",
        granted_scopes=[],
        account_address=None,
        connected_at=None,
    )
    return GoogleConnection(**{**values, **changes})


def connected(address=ADDRESS, **changes):
    values = dict(
        state="connected",
        refresh_token_sealed=seal(EARLIER_REFRESH, REFRESH_TOKEN_PURPOSE),
        granted_scopes=[gmail.SCOPE],
        account_address=address,
    )
    return stored(**{**values, **changes})


class Google:
    """Mocked Google endpoints. Records every request and what the flow did in order."""

    def __init__(self, events):
        self.events = events
        self.requests = []
        self.token = httpx.Response(
            200, json={"access_token": ACCESS, "refresh_token": REFRESH, "scope": BOTH}
        )
        self.profile = httpx.Response(200, json={"emailAddress": ADDRESS})
        self.calendar = httpx.Response(200, json={"id": ADDRESS})
        self.revocation = httpx.Response(200, json={})

    def handler(self, request):
        self.requests.append(request)
        url = str(request.url)
        if url == google_oauth.TOKEN_URL:
            self.events.append("exchange")
            return self.token
        if url == f"{gmail.API_BASE}/profile":
            self.events.append("profile")
            return self.profile
        if url == google_oauth.PRIMARY_CALENDAR_URL:
            self.events.append("calendar")
            return self.calendar
        if url == google_oauth.REVOCATION_URL:
            self.events.append("revoke")
            return self.revocation
        raise AssertionError("request to an unexpected address")

    def sent(self, url):
        return [parse_qs(r.content.decode()) for r in self.requests if str(r.url) == url]


class Flow:
    def __init__(self, client, database, redis, google, events, current):
        self.client = client
        self.database = database
        self.redis = redis
        self.google = google
        self.events = events
        self.current = current

    def start(self, capabilities=("gmail", "calendar"), host=HOST, client=None):
        return (client or self.client).post(
            START, data={"capability": list(capabilities)}, headers={"host": host}
        )

    def started(self, capabilities=("gmail", "calendar"), host=HOST):
        """Start a flow and return its ``state`` as Google would send it back."""
        response = self.start(capabilities, host)
        assert response.status_code == 303
        return parse_qs(urlsplit(response.headers["location"]).query)["state"][0]

    def callback(self, state, client=None, **params):
        query = {"state": state, "code": CODE, **params}
        query = {name: value for name, value in query.items() if value is not None}
        return (client or self.client).get(CALLBACK_PATH, params=query, headers={"host": HOST})

    def row(self):
        return self.database.get.return_value

    def entry(self):
        ((value, _expires),) = self.redis.data.values()
        return json.loads(value)


@pytest.fixture
def flow(monkeypatch):
    """The real application with a fake store, a database double and mocked Google."""
    events = []
    database = MagicMock()
    database.get.return_value = stored()
    database.commit.side_effect = lambda: events.append("commit")
    redis = Redis()
    google = Google(events)
    current = {"settings": ENABLED}
    monkeypatch.setattr(google_consent, "get_settings", lambda: current["settings"])
    monkeypatch.setattr(
        google_consent,
        "_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(google.handler)),
    )
    app.dependency_overrides[get_session] = lambda: database
    app.dependency_overrides[get_flow_store] = lambda: FlowStore(redis)
    try:
        client = TestClient(app, follow_redirects=False)
        yield Flow(client, database, redis, google, events, current)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_flow_store, None)


SECRETS = (CLIENT_SECRET, CODE, ACCESS, REFRESH, EARLIER_REFRESH)


def shown(response):
    """Everything a response carries that a browser or a log could keep."""
    return response.text + " " + " ".join(f"{k}: {v}" for k, v in response.headers.multi_items())


def result_word(response):
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith(RESULT_ADDRESS)
    word = location[len(RESULT_ADDRESS) :]
    assert word in RESULTS  # one of the fixed words and nothing else
    return word


def nothing_stored(flow):
    row = flow.row()
    return (
        "commit" not in flow.events
        and row.state == "not_connected"
        and row.refresh_token_sealed is None
        and row.granted_scopes == []
    )


# ---------- starting the flow ----------


def test_start_redirects_the_browser_to_googles_consent_screen(flow):
    response = flow.start()
    assert response.status_code == 303 and response.content == b""
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    address = urlsplit(response.headers["location"])
    assert f"{address.scheme}://{address.netloc}{address.path}" == google_oauth.AUTHORIZATION_URL
    query = parse_qs(address.query, strict_parsing=True)
    state, challenge = query.pop("state")[0], query.pop("code_challenge")[0]
    assert query == {
        "client_id": [CLIENT_ID],
        "redirect_uri": [f"http://{HOST}{CALLBACK_PATH}"],
        "response_type": ["code"],
        "scope": [BOTH],
        "access_type": ["offline"],
        "prompt": ["consent"],
        "include_granted_scopes": ["true"],
        "code_challenge_method": ["S256"],
    }
    assert len(state) == 43  # 256 random bits
    entry = flow.entry()
    assert 43 <= len(entry["verifier"]) <= 128  # RFC 7636, section 4.1
    assert challenge == google_oauth.code_challenge(entry["verifier"])
    assert entry["verifier"] not in shown(response) and CLIENT_SECRET not in shown(response)
    assert flow.google.requests == []  # the server itself contacts nothing yet


def test_start_sets_a_binding_cookie_limited_to_the_callback(flow):
    response = flow.start()
    (cookie,) = response.headers.get_list("set-cookie")
    name, _, value = cookie.split(";")[0].partition("=")
    assert name.startswith(BINDING_COOKIE_PREFIX) and len(value) == 43
    attributes = {part.strip().lower() for part in cookie.split(";")[1:]}
    assert attributes == {
        "httponly",
        "samesite=lax",
        f"path={CALLBACK_PATH}",
        f"max-age={FLOW_SECONDS}",
    }


def test_the_store_holds_hashes_of_state_and_binding_for_ten_minutes(flow):
    response = flow.start(("calendar",))
    state = parse_qs(urlsplit(response.headers["location"]).query)["state"][0]
    binding = response.headers["set-cookie"].split(";")[0].partition("=")[2]
    ((key, (value, expires)),) = flow.redis.data.items()
    assert key == FLOW_KEY_PREFIX + google_consent._digest(state)
    assert expires == flow.redis.now + FLOW_SECONDS == flow.redis.now + 600
    kept = key + value.decode()
    assert state not in kept and binding not in kept and CLIENT_SECRET not in kept
    assert json.loads(value) == {
        "verifier": flow.entry()["verifier"],
        "redirect_address": f"http://{HOST}{CALLBACK_PATH}",
        "capabilities": ["calendar"],
        "binding": google_consent._digest(binding),
        "client_id": CLIENT_ID,
    }


@pytest.mark.parametrize(
    "capabilities,scope",
    [
        (("gmail",), gmail.SCOPE),
        (("calendar",), google_calendar.SCOPE),
        (("calendar", "gmail"), BOTH),
    ],
)
def test_only_the_selected_capabilities_are_requested(flow, capabilities, scope):
    response = flow.start(capabilities)
    assert parse_qs(urlsplit(response.headers["location"]).query)["scope"] == [scope]


@pytest.mark.parametrize("host", ["127.0.0.1:15173", "localhost:15173", "LOCALHOST:18000"])
def test_the_redirect_address_follows_the_host_the_browser_used(flow, host):
    response = flow.start(host=host)
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["redirect_uri"] == [f"http://{host.lower()}{CALLBACK_PATH}"]


def test_start_refuses_a_host_that_is_not_a_loopback_name(flow):
    # The test client's own host name passes the request boundary in tests only.
    response = flow.start(host="testserver")
    assert response.status_code == 400
    assert response.json() == {"detail": HOST_NOT_LOCAL}
    assert flow.redis.data == {}


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"capability=",
        b"capability=drive",
        b"capability=gmail&capability=gmail",
        b"capability=gmail&capability=calendar&capability=gmail",
        b"capability=gmail&other=1",
        b"other=gmail",
        b"capability",
        b'{"capability": ["gmail"]}',
        b"capability=gmail&" + b"x" * 300,
        "capability=gmäil".encode(),
        b"capability=GMAIL",
    ],
)
def test_start_refuses_anything_but_the_known_capabilities(flow, body):
    response = flow.client.post(START, content=body, headers={"host": HOST})
    assert response.status_code == 422
    assert response.json() == {"detail": INVALID_CAPABILITIES}  # nothing submitted is repeated
    assert flow.redis.data == {} and "set-cookie" not in response.headers


@pytest.mark.parametrize(
    "settings,capabilities",
    [
        (Settings(gmail_sync_enabled=True, token_key=SecretStr(KEY)), ("calendar",)),
        (Settings(gmail_sync_enabled=True, token_key=SecretStr(KEY)), ("gmail", "calendar")),
        (Settings(calendar_sync_enabled=True, token_key=SecretStr(KEY)), ("gmail",)),
        (Settings(calendar_sync_enabled=True, token_key=SecretStr(KEY)), ("gmail", "calendar")),
    ],
)
def test_start_refuses_a_capability_that_is_switched_off(flow, settings, capabilities):
    flow.current["settings"] = settings
    response = flow.start(capabilities)
    assert response.status_code == 409
    assert response.json() == {"detail": CAPABILITY_OFF}
    assert flow.redis.data == {} and not flow.database.method_calls


def test_start_allows_the_one_capability_that_is_switched_on(flow):
    flow.current["settings"] = Settings(calendar_sync_enabled=True, token_key=SecretStr(KEY))
    assert flow.start(("calendar",)).status_code == 303


@pytest.mark.parametrize(
    "settings,status,message",
    [
        (ENABLED.model_copy(update={"fixture_data_mode": True}), 409, FIXTURE_MODE),
        (Settings(token_key=SecretStr(KEY)), 409, SWITCHED_OFF),
        (Settings(gmail_sync_enabled=True, calendar_sync_enabled=True), 503, NO_KEY),
    ],
)
def test_start_refuses_where_no_connection_can_be_stored(flow, settings, status, message):
    flow.current["settings"] = settings
    response = flow.start()
    assert (response.status_code, response.json()) == (status, {"detail": message})
    assert flow.redis.data == {} and not flow.database.method_calls
    assert "set-cookie" not in response.headers


def test_start_refuses_before_a_client_is_saved(flow):
    flow.database.get.return_value = None
    response = flow.start()
    assert (response.status_code, response.json()) == (409, {"detail": NO_CLIENT})
    assert flow.redis.data == {}


def test_start_refuses_a_client_secret_the_key_cannot_open(flow):
    other = Settings(token_key=SecretStr("another-unit-test-only-token-key-0123456789"))
    flow.database.get.return_value = stored(
        client_secret_sealed=seal(CLIENT_SECRET, CLIENT_SECRET_PURPOSE, other)
    )
    response = flow.start()
    assert (response.status_code, response.json()) == (409, {"detail": CLIENT_UNREADABLE})
    assert flow.redis.data == {}


def test_start_reports_a_store_outage(flow):
    flow.redis.fail = True
    response = flow.start()
    assert (response.status_code, response.json()) == (503, {"detail": STORE_UNAVAILABLE})
    assert "set-cookie" not in response.headers and "location" not in response.headers


def test_start_changes_nothing_in_the_database(flow):
    assert flow.start().status_code == 303
    assert nothing_stored(flow)
    flow.database.add.assert_not_called()
    flow.database.execute.assert_not_called()


# ---------- the callback: a completed flow ----------


def test_the_callback_exchanges_the_code_and_stores_the_grant(flow):
    state = flow.started()
    verifier = flow.entry()["verifier"]
    response = flow.callback(state, scope=BOTH)
    assert result_word(response) == "connected"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert flow.events == ["exchange", "profile", "calendar", "commit"]
    assert flow.google.sent(google_oauth.TOKEN_URL) == [
        {
            "code": [CODE],
            "client_id": [CLIENT_ID],
            "client_secret": [CLIENT_SECRET],
            "redirect_uri": [f"http://{HOST}{CALLBACK_PATH}"],
            "grant_type": ["authorization_code"],
            "code_verifier": [verifier],
        }
    ]
    row = flow.row()
    assert row.state == "connected" and row.key_version == 1
    assert row.granted_scopes == sorted([gmail.SCOPE, google_calendar.SCOPE])
    assert row.account_address == ADDRESS
    assert row.connected_at is not None and row.connected_at == row.updated_at
    assert REFRESH not in row.refresh_token_sealed
    opened = token_vault.open_sealed(
        row.refresh_token_sealed, purpose=REFRESH_TOKEN_PURPOSE, settings=ENABLED
    )
    assert opened == REFRESH
    # The change was made under the row lock, on a row read again from the database.
    assert flow.database.get.call_args_list[-1].kwargs == {
        "with_for_update": True,
        "populate_existing": True,
    }


def test_the_callback_removes_the_binding_cookie_and_the_entry(flow):
    state = flow.started()
    (name,) = [c.name for c in flow.client.cookies.jar]
    response = flow.callback(state)
    (cookie,) = response.headers.get_list("set-cookie")
    assert cookie.startswith(f'{name}="";') and "max-age=0" in cookie.lower()
    assert f"path={CALLBACK_PATH}" in cookie.lower()
    assert flow.redis.data == {}


def test_nothing_secret_reaches_the_browser_or_a_log(flow, caplog):
    caplog.set_level(logging.DEBUG)
    state = flow.started()
    verifier = flow.entry()["verifier"]
    response = flow.callback(state)
    assert result_word(response) == "connected"
    for value in (*SECRETS, verifier, state):
        assert value not in shown(response)
        assert value not in caplog.text
    assert not [r for r in caplog.records if r.name == google_consent.__name__]


def test_a_state_works_once(flow):
    state = flow.started()
    kept = {cookie.name: cookie.value for cookie in flow.client.cookies.jar}
    assert result_word(flow.callback(state)) == "connected"
    flow.events.clear()
    # A browser that still holds the binding cookie replays the same address.
    replay = flow.callback(state, client=TestClient(app, follow_redirects=False, cookies=kept))
    assert (replay.status_code, replay.json()) == (400, {"detail": FLOW_REFUSED})
    assert flow.events == []  # no second exchange, nothing stored again
    assert replay.headers["referrer-policy"] == "no-referrer"


def test_two_flows_in_one_browser_each_complete(flow):
    first, second = flow.started(("gmail",)), flow.started(("calendar",))
    assert len(flow.client.cookies.jar) == 2
    assert result_word(flow.callback(first)) == "connected"
    assert result_word(flow.callback(second)) == "connected"
    assert flow.events.count("commit") == 2


# ---------- the callback: refusals that exchange and store nothing ----------


def refused(flow, response):
    return (
        (response.status_code, response.json()) == (400, {"detail": FLOW_REFUSED})
        and response.headers["referrer-policy"] == "no-referrer"
        and flow.events == []
        and flow.google.requests == []
        and nothing_stored(flow)
    )


@pytest.mark.parametrize(
    "state",
    [None, "", "unknown", "x" * 43, "x" * 44, "A" * 42 + "!", "A" * 5000],
)
def test_the_callback_refuses_a_missing_malformed_or_unknown_state(flow, state):
    flow.started()
    assert refused(flow, flow.callback(state))


def test_the_callback_refuses_a_repeated_state_parameter(flow):
    state = flow.started()
    response = flow.client.get(
        f"{CALLBACK_PATH}?state={state}&state={state}&code={CODE}", headers={"host": HOST}
    )
    assert refused(flow, response)


def test_the_callback_refuses_without_the_binding_cookie_and_spends_the_state(flow):
    state = flow.started()
    other_browser = TestClient(app, follow_redirects=False)
    assert refused(flow, flow.callback(state, client=other_browser))
    # The entry was deleted as it was read, so the right browser is refused as well.
    assert refused(flow, flow.callback(state))


def test_the_callback_refuses_a_wrong_binding_value(flow):
    state = flow.started()
    (name,) = [c.name for c in flow.client.cookies.jar]
    other_browser = TestClient(app, follow_redirects=False, cookies={name: "x" * 43})
    assert refused(flow, flow.callback(state, client=other_browser))


def test_the_binding_cookie_of_one_flow_does_not_complete_another(flow):
    first = flow.started()
    (first_cookie,) = list(flow.client.cookies.jar)
    flow.client.cookies.clear()
    second = flow.started()
    (second_cookie,) = list(flow.client.cookies.jar)
    # A browser that holds the first flow's value under the second flow's name.
    crossed = TestClient(
        app, follow_redirects=False, cookies={second_cookie.name: first_cookie.value}
    )
    assert refused(flow, flow.callback(second, client=crossed))
    assert first != second


def test_the_callback_refuses_an_expired_flow(flow):
    state = flow.started()
    flow.redis.now += FLOW_SECONDS + 1
    assert refused(flow, flow.callback(state))


def test_the_callback_reports_a_store_outage(flow):
    state = flow.started()
    flow.redis.fail = True
    response = flow.callback(state)
    assert (response.status_code, response.json()) == (503, {"detail": STORE_UNAVAILABLE})
    assert flow.events == [] and nothing_stored(flow)


@pytest.mark.parametrize(
    "settings,status,message",
    [
        (ENABLED.model_copy(update={"fixture_data_mode": True}), 409, FIXTURE_MODE),
        (Settings(token_key=SecretStr(KEY)), 409, SWITCHED_OFF),
        (Settings(gmail_sync_enabled=True), 503, NO_KEY),
    ],
)
def test_the_callback_refuses_where_no_connection_can_be_stored(flow, settings, status, message):
    state = flow.started()
    flow.current["settings"] = settings
    response = flow.callback(state)
    assert (response.status_code, response.json()) == (status, {"detail": message})
    assert response.headers["referrer-policy"] == "no-referrer"
    assert flow.events == [] and len(flow.redis.data) == 1  # refused before the state is read


def test_the_callback_needs_no_session(flow):
    """Google's redirect arrives without the session cookie; the flow checks stand in."""
    state = flow.started()
    # The real requirement applies again, against an empty session store.
    app.dependency_overrides.pop(require_session)
    app.dependency_overrides[get_store] = lambda: SessionStore(Redis())
    try:
        assert flow.start().status_code == 401
        assert flow.callback(state).status_code == 303
    finally:
        app.dependency_overrides.pop(get_store, None)


# ---------- the callback: outcomes after the flow checks pass ----------


@pytest.mark.parametrize(
    "error,word",
    [
        ("access_denied", "declined"),
        ("server_error", "failed"),
        ("GOOGLE-TEXT-THAT-MUST-NOT-BE-REPEATED", "failed"),
        ("", "failed"),
    ],
)
def test_a_decline_or_error_at_google_stores_nothing(flow, error, word):
    state = flow.started()
    response = flow.callback(state, code=None, error=error)
    assert result_word(response) == word
    assert "GOOGLE-TEXT" not in shown(response)
    assert flow.events == [] and flow.google.requests == [] and nothing_stored(flow)
    assert flow.redis.data == {}  # the state is spent


def test_a_decline_leaves_an_existing_connection_as_it_was(flow):
    flow.database.get.return_value = row = connected()
    before = (row.refresh_token_sealed, row.state, list(row.granted_scopes), row.account_address)
    state = flow.started()
    assert result_word(flow.callback(state, code=None, error="access_denied")) == "declined"
    after = (row.refresh_token_sealed, row.state, list(row.granted_scopes), row.account_address)
    assert after == before and flow.events == []


@pytest.mark.parametrize("code", [None, "", "has space", "x" * 2049, "café"])
def test_a_missing_or_malformed_code_is_not_sent_to_google(flow, code):
    state = flow.started()
    assert result_word(flow.callback(state, code=code)) == "failed"
    assert flow.google.requests == [] and nothing_stored(flow)


@pytest.mark.parametrize(
    "token",
    [
        httpx.Response(400, json={"error": "invalid_grant", "error_description": "GOOGLE-TEXT"}),
        httpx.Response(500, text="GOOGLE-TEXT"),
        httpx.Response(200, text="GOOGLE-TEXT"),
        httpx.Response(200, json={"access_token": ACCESS, "refresh_token": REFRESH}),
    ],
)
def test_a_failed_exchange_stores_nothing_and_is_not_retried(flow, token):
    flow.google.token = token
    state = flow.started()
    response = flow.callback(state)
    assert result_word(response) == "failed"
    assert "GOOGLE-TEXT" not in shown(response)
    assert flow.events == ["exchange"] and nothing_stored(flow)  # one attempt, no revocation


def test_an_unreachable_google_stores_nothing(flow, monkeypatch):
    def unreachable(request):
        raise httpx.ConnectError("synthetic outage")

    monkeypatch.setattr(
        google_consent,
        "_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(unreachable)),
    )
    state = flow.started()
    assert result_word(flow.callback(state)) == "failed"
    assert nothing_stored(flow)


def test_an_exchange_without_a_refresh_token_stores_nothing(flow):
    flow.google.token = httpx.Response(200, json={"access_token": ACCESS, "scope": BOTH})
    state = flow.started()
    assert result_word(flow.callback(state)) == "failed"
    assert flow.events == ["exchange"] and nothing_stored(flow)


@pytest.mark.parametrize("scope", ["", "openid", "https://www.googleapis.com/auth/gmail.modify"])
def test_a_grant_of_neither_capability_is_revoked_and_not_stored(flow, scope):
    flow.google.token = httpx.Response(
        200, json={"access_token": ACCESS, "refresh_token": REFRESH, "scope": scope}
    )
    state = flow.started()
    assert result_word(flow.callback(state)) == "not_granted"
    assert flow.events == ["exchange", "revoke"] and nothing_stored(flow)
    assert flow.google.sent(google_oauth.REVOCATION_URL) == [{"token": [REFRESH]}]


def test_a_grant_of_neither_capability_without_a_refresh_token_revokes_the_access_token(flow):
    flow.google.token = httpx.Response(200, json={"access_token": ACCESS, "scope": "openid"})
    state = flow.started()
    assert result_word(flow.callback(state)) == "not_granted"
    assert flow.google.sent(google_oauth.REVOCATION_URL) == [{"token": [ACCESS]}]
    assert nothing_stored(flow)


@pytest.mark.parametrize(
    "asked,scope",
    [
        (("calendar",), gmail.SCOPE),
        (("gmail",), google_calendar.SCOPE),
        (("gmail",), f"openid {google_calendar.SCOPE}"),
    ],
)
def test_a_grant_that_covers_only_what_was_not_asked_for_is_not_stored(flow, asked, scope):
    """An earlier grant can still be listed after the user declines what was asked now."""
    flow.google.token = httpx.Response(
        200, json={"access_token": ACCESS, "refresh_token": REFRESH, "scope": scope}
    )
    state = flow.started(asked)
    assert result_word(flow.callback(state)) == "not_granted"
    assert flow.events == ["exchange", "revoke"] and nothing_stored(flow)


@pytest.mark.parametrize("scope", ["", "openid", gmail.SCOPE])
def test_a_refused_request_never_revokes_while_a_grant_is_stored(flow, scope):
    """Revoking ends the account's whole grant, which may be the stored connection."""
    flow.database.get.return_value = row = connected()
    before = (row.refresh_token_sealed, row.state, list(row.granted_scopes), row.account_address)
    flow.google.token = httpx.Response(
        200, json={"access_token": ACCESS, "refresh_token": REFRESH, "scope": scope}
    )
    state = flow.started(("calendar",))
    assert result_word(flow.callback(state)) == "not_granted"
    assert flow.events == ["exchange"]  # no revocation, no account lookup, nothing stored
    after = (row.refresh_token_sealed, row.state, list(row.granted_scopes), row.account_address)
    assert after == before


def test_a_refused_request_never_revokes_while_the_fallback_is_configured(flow):
    flow.current["settings"] = ENABLED.model_copy(
        update={
            "google_oauth_client_id": SecretStr("synthetic-fallback-client"),
            "google_oauth_client_secret": SecretStr("synthetic-fallback-secret"),
            "gmail_refresh_token": SecretStr("synthetic-fallback-token"),
        }
    )
    flow.google.token = httpx.Response(
        200, json={"access_token": ACCESS, "refresh_token": REFRESH, "scope": "openid"}
    )
    state = flow.started()
    assert result_word(flow.callback(state)) == "not_granted"
    assert flow.events == ["exchange"] and nothing_stored(flow)


@pytest.mark.parametrize(
    "scope,lookups,granted",
    [
        (gmail.SCOPE, ["profile"], [gmail.SCOPE]),
        (google_calendar.SCOPE, ["calendar"], [google_calendar.SCOPE]),
    ],
)
def test_a_partial_grant_is_stored_with_what_was_actually_granted(flow, scope, lookups, granted):
    flow.google.token = httpx.Response(
        200, json={"access_token": ACCESS, "refresh_token": REFRESH, "scope": scope}
    )
    state = flow.started(("gmail", "calendar"))
    assert result_word(flow.callback(state)) == "connected"
    assert flow.events == ["exchange", *lookups, "commit"]
    assert flow.row().state == "connected" and flow.row().granted_scopes == granted


def test_the_stored_scopes_are_what_google_returned_not_what_was_asked(flow):
    extra = "https://www.googleapis.com/auth/userinfo.email"
    flow.google.token = httpx.Response(
        200,
        json={"access_token": ACCESS, "refresh_token": REFRESH, "scope": f"{BOTH} {extra}"},
    )
    state = flow.started(("calendar",))
    assert result_word(flow.callback(state)) == "connected"
    assert flow.row().granted_scopes == sorted([gmail.SCOPE, google_calendar.SCOPE, extra])


@pytest.mark.parametrize(
    "profile",
    [httpx.Response(503), httpx.Response(403), httpx.Response(200, json={"emailAddress": ""})],
)
def test_a_grant_whose_account_cannot_be_read_is_not_stored_or_revoked(flow, profile):
    flow.google.profile = profile
    state = flow.started()
    assert result_word(flow.callback(state)) == "failed"
    assert flow.events == ["exchange", "profile"] and nothing_stored(flow)


def test_a_grant_is_not_stored_unless_every_lookup_of_the_account_succeeds(flow):
    flow.google.calendar = httpx.Response(503)
    state = flow.started()
    assert result_word(flow.callback(state)) == "failed"
    assert flow.events == ["exchange", "profile", "calendar"] and nothing_stored(flow)


def opened_refresh_token(flow):
    return token_vault.open_sealed(
        flow.row().refresh_token_sealed, purpose=REFRESH_TOKEN_PURPOSE, settings=ENABLED
    )


def test_the_same_account_replaces_its_grant_without_a_revocation(flow):
    flow.database.get.return_value = connected(address="Person@Example.Test")
    state = flow.started()
    assert result_word(flow.callback(state)) == "connected"
    # Revoking would end the new grant as well.
    assert flow.events == ["exchange", "profile", "calendar", "commit"]
    assert opened_refresh_token(flow) == REFRESH


def test_the_same_account_is_recognized_by_either_of_its_addresses(flow):
    """Connected with Calendar only, then Gmail is added: the stored address is the
    calendar's, and the mailbox may name the account differently."""
    flow.database.get.return_value = connected(
        address="calendar.name@example.test", granted_scopes=[google_calendar.SCOPE]
    )
    flow.google.profile = httpx.Response(200, json={"emailAddress": "mailbox.name@example.test"})
    flow.google.calendar = httpx.Response(200, json={"id": "Calendar.Name@example.test"})
    state = flow.started(("gmail",))
    assert result_word(flow.callback(state)) == "connected"
    assert "revoke" not in flow.events
    assert flow.row().account_address == "mailbox.name@example.test"
    assert opened_refresh_token(flow) == REFRESH


def test_a_different_account_has_the_earlier_grant_revoked_once_the_new_one_is_stored(flow):
    flow.database.get.return_value = connected(address="earlier@example.test")
    state = flow.started()
    assert result_word(flow.callback(state)) == "connected"
    assert flow.events == ["exchange", "profile", "calendar", "commit", "revoke"]
    assert flow.google.sent(google_oauth.REVOCATION_URL) == [{"token": [EARLIER_REFRESH]}]
    assert flow.row().account_address == ADDRESS
    assert opened_refresh_token(flow) == REFRESH


def test_a_different_account_that_cannot_be_stored_leaves_the_earlier_grant_alone(flow):
    flow.database.get.return_value = connected(address="earlier@example.test")
    flow.database.commit.side_effect = RuntimeError("synthetic database failure")
    state = flow.started()
    assert result_word(flow.callback(state)) == "failed"
    assert "revoke" not in flow.events  # the earlier connection still works


@pytest.mark.parametrize("revocation", [httpx.Response(400), httpx.Response(503)])
def test_a_failed_revocation_of_the_earlier_grant_is_reported(flow, revocation):
    flow.database.get.return_value = connected(address="earlier@example.test")
    flow.google.revocation = revocation
    state = flow.started()
    assert result_word(flow.callback(state)) == "connected_earlier_not_revoked"
    assert flow.events == ["exchange", "profile", "calendar", "commit", "revoke"]
    assert flow.row().account_address == ADDRESS


def test_a_revocation_that_breaks_does_not_change_what_was_stored(flow, monkeypatch):
    flow.database.get.return_value = connected(address="earlier@example.test")

    def broken(client, settings, token):
        raise RuntimeError("synthetic failure naming " + token)

    monkeypatch.setattr(google_oauth, "revoke", broken)
    state = flow.started()
    assert result_word(flow.callback(state)) == "connected_earlier_not_revoked"
    assert flow.events[-1] == "commit" and opened_refresh_token(flow) == REFRESH


def test_an_earlier_grant_that_cannot_be_opened_is_reported_as_not_revoked(flow):
    other = Settings(token_key=SecretStr("another-unit-test-only-token-key-0123456789"))
    flow.database.get.return_value = connected(
        address="earlier@example.test",
        refresh_token_sealed=seal(EARLIER_REFRESH, REFRESH_TOKEN_PURPOSE, other),
    )
    state = flow.started()
    assert result_word(flow.callback(state)) == "connected_earlier_not_revoked"
    assert flow.events == ["exchange", "profile", "calendar", "commit"]


def test_an_earlier_grant_of_an_unknown_account_is_never_revoked(flow):
    flow.database.get.return_value = connected(address=None)
    state = flow.started()
    assert result_word(flow.callback(state)) == "connected_earlier_not_revoked"
    assert "revoke" not in flow.events


def test_a_client_replaced_during_the_flow_stores_nothing(flow):
    state = flow.started()
    other = "123456789012-another0client.apps.googleusercontent.com"
    flow.database.get.return_value = stored(client_id=other)
    assert result_word(flow.callback(state)) == "failed"
    assert flow.events == [] and nothing_stored(flow)


def test_a_client_replaced_while_google_was_contacted_stores_nothing(flow):
    state = flow.started()
    other = stored(client_id="123456789012-another0client.apps.googleusercontent.com")
    first = flow.row()
    flow.database.get.side_effect = lambda *args, **kwargs: (
        other if kwargs.get("with_for_update") else first
    )
    assert result_word(flow.callback(state)) == "failed"
    assert flow.events == ["exchange", "profile", "calendar"]
    assert other.refresh_token_sealed is None and first.refresh_token_sealed is None
    # Once before Google is contacted, and once to give up the row lock.
    assert flow.database.rollback.call_count == 2


def test_a_client_secret_that_cannot_be_opened_stores_nothing(flow):
    state = flow.started()
    other = Settings(token_key=SecretStr("another-unit-test-only-token-key-0123456789"))
    flow.database.get.return_value = stored(
        client_secret_sealed=seal(CLIENT_SECRET, CLIENT_SECRET_PURPOSE, other)
    )
    assert result_word(flow.callback(state)) == "failed"
    assert flow.google.requests == []


def test_an_unexpected_failure_is_logged_by_type_only(flow, caplog):
    state = flow.started()
    flow.database.commit.side_effect = RuntimeError("detail naming " + REFRESH)
    caplog.set_level(logging.DEBUG)
    response = flow.callback(state)
    assert result_word(response) == "failed"
    assert response.headers["referrer-policy"] == "no-referrer"
    (record,) = [r for r in caplog.records if r.name == google_consent.__name__]
    assert record.getMessage() == "Google connection callback failed (RuntimeError)"
    assert record.exc_info is None
    for value in (*SECRETS, state):
        assert value not in caplog.text
    # Once before Google is contacted, and once after the failure.
    assert flow.database.rollback.call_count == 2


def test_a_failure_while_cleaning_up_is_still_a_result_word(flow):
    state = flow.started()
    flow.database.get.side_effect = RuntimeError("synthetic database failure")
    flow.database.rollback.side_effect = RuntimeError("synthetic database failure")
    assert result_word(flow.callback(state)) == "failed"


@pytest.mark.parametrize(
    "token,code",
    [
        (httpx.Response(400, json={"error": "GOOGLE-TEXT"}), "exchange_refused"),
        (httpx.Response(503, text="GOOGLE-TEXT"), "provider_unavailable"),
        (httpx.Response(200, text="GOOGLE-TEXT"), "invalid_response"),
    ],
)
def test_an_expected_failure_is_logged_by_its_fixed_code_only(flow, caplog, token, code):
    flow.google.token = token
    state = flow.started()
    caplog.set_level(logging.DEBUG)
    assert result_word(flow.callback(state)) == "failed"
    (record,) = [r for r in caplog.records if r.name == google_consent.__name__]
    assert record.getMessage() == f"Google connection not completed ({code})"
    for value in (*SECRETS, state, "GOOGLE-TEXT"):
        assert value not in caplog.text


def test_a_store_outage_is_an_expected_failure(flow):
    """``RedisError`` on the read is answered directly, not through the catch-all."""
    state = flow.started()
    flow.redis.getdel = MagicMock(side_effect=RedisConnectionError("synthetic outage"))
    assert flow.callback(state).status_code == 503


# ---------- the access log ----------


def access_record(target, status=400):
    """A record as Uvicorn's HTTP protocol classes create it."""
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:50000", "GET", target, "1.1", status),
        None,
    )


@pytest.mark.parametrize(
    "target,logged",
    [
        (f"{CALLBACK_PATH}?state=S&code={CODE}", CALLBACK_PATH),
        (f"{CALLBACK_PATH}?error=access_denied&state=S", CALLBACK_PATH),
        (f"{CALLBACK_PATH}/?code={CODE}", CALLBACK_PATH + "/"),
        (f"{CALLBACK_PATH}x?code={CODE}", CALLBACK_PATH + "x"),
        (CALLBACK_PATH, CALLBACK_PATH),
        ("/api/jobs?search=qa", "/api/jobs?search=qa"),
        ("/api/google/connection?x=1", "/api/google/connection?x=1"),
    ],
)
def test_the_filter_cuts_the_query_string_of_the_callback_only(target, logged):
    record = access_record(target)
    assert CallbackQueryFilter().filter(record) is True
    assert record.getMessage() == f'127.0.0.1:50000 - "GET {logged} HTTP/1.1" 400'
    assert CODE not in record.getMessage()


@pytest.mark.parametrize(
    "record",
    [
        logging.LogRecord(
            "uvicorn.access", 20, __file__, 0, f"GET {CALLBACK_PATH}?code={CODE}", None, None
        ),
        logging.LogRecord(
            "uvicorn.access", 20, __file__, 0, "%s", (f"GET {CALLBACK_PATH}?code={CODE}",), None
        ),
        logging.LogRecord(
            "uvicorn.access",
            20,
            __file__,
            0,
            "%(t)s",
            ({"t": f"{CALLBACK_PATH}?code={CODE}"},),
            None,
        ),
        logging.LogRecord("uvicorn.access", 20, __file__, 0, "%d %d", (CALLBACK_PATH,), None),
    ],
)
def test_a_record_the_filter_cannot_cut_is_dropped(record):
    assert CallbackQueryFilter().filter(record) is False


def test_the_application_installs_the_filter_once():
    access = logging.getLogger("uvicorn.access")
    assert access.filters.count(google_consent._access_log_filter) == 1
    google_consent.protect_access_log()
    assert access.filters.count(google_consent._access_log_filter) == 1


def test_a_running_server_writes_the_callback_to_its_access_log_without_the_query(flow):
    """The real server, with its own logging configuration, on a loopback port."""
    lines = []

    class Capture(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    access = logging.getLogger("uvicorn.access")
    names = ("uvicorn", "uvicorn.error", "uvicorn.access")
    before = {
        name: (logger.handlers[:], logger.propagate, logger.level)
        for name, logger in ((name, logging.getLogger(name)) for name in names)
    }
    config = uvicorn.Config(app, host="127.0.0.1", port=0, lifespan="off")
    server = uvicorn.Server(config)  # applies Uvicorn's default logging configuration
    capture = Capture()
    access.addHandler(capture)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        port = server.servers[0].sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        state = "S" * 43
        with httpx.Client(trust_env=False, timeout=10) as client:
            refusal = client.get(f"{base}{CALLBACK_PATH}", params={"state": state, "code": CODE})
            other = client.get(f"{base}/api/live", params={"marker": "kept"})
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        # Put the loggers back as they were, so the server's handlers do not outlive the test.
        for name, (handlers, propagate, level) in before.items():
            logger = logging.getLogger(name)
            logger.handlers[:] = handlers
            logger.propagate, logger.level = propagate, level
    assert refusal.status_code == 400 and other.status_code == 200
    written = "\n".join(lines)
    assert f'"GET {CALLBACK_PATH} HTTP/1.1" 400' in written
    assert '"GET /api/live?marker=kept HTTP/1.1" 200' in written  # other routes are untouched
    assert CODE not in written and state not in written and "?state" not in written
