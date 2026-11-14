"""Local session routes and store (docs/decisions/0001-local-session-boundary.md, layer 3)."""

import logging

import pytest
import route_helpers
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from redis.exceptions import ConnectionError as RedisConnectionError

from app import local_session
from app.config import ConfigError, Settings, load_settings
from app.local_session import (
    COOKIE_NAME,
    IDLE_SECONDS,
    KEY_PREFIX,
    MAX_SECONDS,
    SessionStore,
    get_store,
    require_session,
)
from app.main import app as real_app

CODE = "synthetic-setup-code-for-unit-tests-only"
NOW = 1_800_000_000.0


class FakeRedis:
    """The four commands the store uses, with expiry driven by a settable clock."""

    def __init__(self):
        self.now = NOW
        self.data = {}  # key -> (value, expires_at)
        self.fail = False

    def _live(self, key):
        if self.fail:
            raise RedisConnectionError("synthetic outage")
        item = self.data.get(key)
        if item and item[1] <= self.now:
            del self.data[key]
            return None
        return item

    def set(self, key, value, ex):
        self._live(key)
        self.data[key] = (value.encode(), self.now + ex)

    def get(self, key):
        item = self._live(key)
        return item[0] if item else None

    def expire(self, key, seconds):
        item = self._live(key)
        if item:
            self.data[key] = (item[0], self.now + seconds)

    def delete(self, key):
        self._live(key)
        self.data.pop(key, None)


@pytest.fixture
def redis():
    return FakeRedis()


@pytest.fixture
def client(monkeypatch, redis):
    """The session routes plus one protected route, with a synthetic setup code."""
    monkeypatch.setattr(local_session, "get_settings", lambda: Settings(setup_code=SecretStr(CODE)))
    monkeypatch.setattr(local_session.time, "time", lambda: redis.now)
    monkeypatch.setattr(local_session.time, "sleep", lambda seconds: delays.append(seconds))
    delays.clear()
    inner = FastAPI()
    inner.include_router(local_session.router)

    @inner.get("/api/protected", dependencies=[Depends(require_session)])
    def protected():
        return {"reached": True}

    inner.dependency_overrides[get_store] = lambda: SessionStore(redis)
    return TestClient(inner, base_url="http://127.0.0.1:18000")


delays: list[float] = []


def start(client, code=CODE):
    return client.post("/api/session", json={"code": code})


# ---------- starting a session ----------


def test_correct_code_starts_a_session_with_a_restricted_cookie(client, redis):
    response = start(client)
    assert response.status_code == 204 and response.content == b""
    cookie = response.headers["set-cookie"]
    identifier = response.cookies[COOKIE_NAME]
    assert len(identifier) >= 43
    attributes = {part.strip().lower() for part in cookie.split(";")[1:]}
    assert attributes == {"httponly", "samesite=strict", "path=/api", f"max-age={MAX_SECONDS}"}
    assert client.get("/api/session").json() == {"configured": True, "active": True}
    assert client.get("/api/protected").json() == {"reached": True}


def test_only_a_hash_of_the_identifier_is_stored(client, redis):
    identifier = start(client).cookies[COOKIE_NAME]
    (key,) = redis.data
    assert key.startswith(KEY_PREFIX) and identifier not in key
    assert identifier.encode() not in redis.data[key][0]
    assert CODE not in key and CODE.encode() not in redis.data[key][0]


@pytest.mark.parametrize("code", ["wrong", CODE + "x", CODE[:-1], CODE.upper(), " " + CODE])
def test_wrong_code_is_refused_after_a_fixed_delay(client, redis, code, caplog):
    caplog.set_level(logging.DEBUG)
    response = start(client, code)
    assert response.status_code == 401
    assert response.json() == {"detail": local_session.SESSION_REFUSED}
    assert "set-cookie" not in response.headers and not redis.data
    assert delays == [local_session.FAILURE_DELAY_SECONDS]
    assert code not in response.text and code not in caplog.text and CODE not in caplog.text


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        b"[]",
        b'"' + CODE.encode() + b'"',
        b"{}",
        b'{"code": ""}',
        b'{"code": 7}',
        b'{"code": null}',
        b'{"code": "' + CODE.encode() + b'", "extra": 1}',
        b'{"Code": "' + CODE.encode() + b'"}',
        b'{"code": "' + b"x" * 513 + b'"}',
        b'{"code": "' + CODE.encode() + b'", "pad": "' + b"x" * 3000 + b'"}',
    ],
)
def test_malformed_requests_get_a_fixed_error_that_never_echoes_the_input(client, redis, body):
    response = client.post(
        "/api/session", content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422 and not redis.data
    assert response.json() == {"detail": local_session.INVALID_REQUEST}


@pytest.mark.parametrize("configured", ["", "too-short"])
def test_sessions_cannot_start_without_a_usable_setup_code(client, monkeypatch, redis, configured):
    monkeypatch.setattr(
        local_session, "get_settings", lambda: Settings(setup_code=SecretStr(configured))
    )
    response = start(client, configured or "anything")
    assert response.status_code == 503
    assert response.json() == {"detail": local_session.NOT_CONFIGURED}
    assert not redis.data
    assert client.get("/api/session").json() == {"configured": False, "active": False}


# ---------- requiring and ending a session ----------


def test_protected_route_refuses_without_a_session(client):
    response = client.get("/api/protected")
    assert response.status_code == 401
    assert response.json() == {"detail": local_session.SESSION_REQUIRED}
    assert client.get("/api/session").json() == {"configured": True, "active": False}


def test_unknown_identifier_is_refused(client):
    client.cookies.set(COOKIE_NAME, "not-a-session", path="/api")
    assert client.get("/api/protected").status_code == 401


def test_ending_a_session_removes_it_and_clears_the_cookie(client, redis):
    identifier = start(client).cookies[COOKIE_NAME]
    response = client.delete("/api/session")
    assert response.status_code == 204 and not redis.data
    cleared = response.headers["set-cookie"].lower()
    assert f"{COOKIE_NAME}=" in cleared and "max-age=0" in cleared and "path=/api" in cleared
    client.cookies.set(COOKIE_NAME, identifier, path="/api")  # a copy kept elsewhere
    assert client.get("/api/protected").status_code == 401


def test_ending_without_a_session_is_harmless(client):
    assert client.delete("/api/session").status_code == 204


def test_each_session_gets_a_distinct_identifier(client, redis):
    first = start(client).cookies[COOKIE_NAME]
    second = start(client).cookies[COOKIE_NAME]
    assert first != second and len(redis.data) == 2


# ---------- expiry ----------


def test_session_expires_after_the_idle_limit(client, redis):
    start(client)
    redis.now += IDLE_SECONDS - 1
    assert client.get("/api/protected").status_code == 200  # use restarts the idle limit
    redis.now += IDLE_SECONDS - 1
    assert client.get("/api/protected").status_code == 200
    redis.now += IDLE_SECONDS + 1
    assert client.get("/api/protected").status_code == 401
    assert not redis.data


def test_session_ends_at_the_absolute_limit_even_when_in_use(client, redis):
    start(client)
    elapsed = 0
    step = IDLE_SECONDS // 2
    while elapsed + step < MAX_SECONDS:
        redis.now += step
        elapsed += step
        assert client.get("/api/protected").status_code == 200, elapsed
    redis.now += step
    assert client.get("/api/protected").status_code == 401


def test_idle_limit_never_extends_past_the_absolute_limit(redis):
    store = SessionStore(redis)
    identifier = store.create(NOW)
    redis.now = NOW + MAX_SECONDS - 60
    redis.data = {k: (v, redis.now + 10) for k, (v, _) in redis.data.items()}
    assert store.touch(identifier, redis.now)
    ((_, expires_at),) = redis.data.values()
    assert expires_at == NOW + MAX_SECONDS


def test_corrupt_stored_value_is_treated_as_expired(redis):
    store = SessionStore(redis)
    identifier = store.create(NOW)
    (key,) = redis.data
    redis.data[key] = (b"not-a-number", NOW + 100)
    assert not store.touch(identifier, NOW) and not redis.data


# ---------- store outage ----------


def test_store_outage_is_a_fixed_503_and_never_grants_access(client, redis, caplog):
    identifier = start(client).cookies[COOKIE_NAME]
    redis.fail = True
    for response in (
        client.get("/api/protected"),
        client.get("/api/session"),
        start(client),
        client.delete("/api/session"),
    ):
        assert response.status_code == 503
        assert response.json() == {"detail": local_session.STORE_UNAVAILABLE}
    assert "synthetic outage" not in caplog.text and identifier not in caplog.text


# ---------- configuration ----------


def environment(**extra):
    return {
        "NEXTUP_ENV": "dev",
        "NEXTUP_DB_HOST": "postgres",
        "NEXTUP_DB_NAME": "nextup_dev",
        "NEXTUP_DB_USER": "nextup_dev_app",
        "NEXTUP_DB_PASSWORD": "unit_test_only_not_a_real_password",
        **extra,
    }


def test_setup_code_is_read_from_a_file_only(tmp_path, monkeypatch):
    assert load_settings(environment()).setup_code.get_secret_value() == ""
    with pytest.raises(ConfigError) as refused:
        load_settings(environment(NEXTUP_SETUP_CODE=CODE))
    assert refused.value.code == "NXG-C16" and CODE not in str(refused.value)


def test_setup_code_never_appears_in_settings_repr():
    settings = Settings(setup_code=SecretStr(CODE))
    assert CODE not in repr(settings) and CODE not in str(settings)


# ---------- the real application ----------


def test_the_application_serves_the_session_routes(monkeypatch, redis):
    monkeypatch.setattr(local_session, "get_settings", lambda: Settings(setup_code=SecretStr(CODE)))
    real_app.dependency_overrides[get_store] = lambda: SessionStore(redis)
    try:
        client = TestClient(real_app)
        assert client.get("/api/session").json() == {"configured": True, "active": False}
        assert start(client).status_code == 204
        assert client.get("/api/session").json() == {"configured": True, "active": True}
    finally:
        real_app.dependency_overrides.pop(get_store, None)


# ---------- routes that require a session ----------

PROTECTED = [
    ("PUT", "/api/correspondence"),
    ("POST", "/api/correspondence/sync"),
]


@pytest.fixture
def app_client(monkeypatch, redis):
    """The real application with a fake store and a database that must not be touched."""
    from unittest.mock import MagicMock

    from app.db import get_session

    database = MagicMock()
    database.get.return_value = None
    database.scalar.return_value = 0
    monkeypatch.setattr(local_session, "get_settings", lambda: Settings(setup_code=SecretStr(CODE)))
    monkeypatch.setattr(local_session.time, "time", lambda: redis.now)
    real_app.dependency_overrides[get_store] = lambda: SessionStore(redis)
    real_app.dependency_overrides[get_session] = lambda: database
    try:
        yield TestClient(real_app), database
    finally:
        real_app.dependency_overrides.pop(get_store, None)
        real_app.dependency_overrides.pop(get_session, None)


@pytest.mark.parametrize("method,path", PROTECTED)
@pytest.mark.parametrize("body", [None, {"enabled": True}, {"enabled": "not-a-boolean"}])
def test_protected_routes_refuse_without_a_session_before_anything_else(
    app_client, method, path, body
):
    client, database = app_client
    response = client.request(method, path, json=body)
    assert response.status_code == 401
    assert response.json() == {"detail": local_session.SESSION_REQUIRED}
    assert not database.method_calls  # refused before validation or any database work


@pytest.mark.parametrize("method,path", PROTECTED)
def test_protected_routes_are_reached_with_a_session(app_client, monkeypatch, method, path):
    client, _ = app_client
    monkeypatch.setattr("app.correspondence.get_settings", lambda: Settings())
    assert start(client).status_code == 204
    response = client.request(method, path, json={"enabled": "not-a-boolean"})
    # Past the session check: the route's own validation or state answers instead.
    assert response.status_code in (409, 422)


@pytest.mark.parametrize("method,path", PROTECTED)
def test_protected_routes_refuse_again_after_the_session_ends(app_client, method, path):
    client, _ = app_client
    start(client)
    assert client.delete("/api/session").status_code == 204
    assert client.request(method, path, json={}).status_code == 401


def test_reading_sync_settings_needs_no_session(app_client, monkeypatch):
    client, _ = app_client
    monkeypatch.setattr("app.correspondence.get_settings", lambda: Settings())
    assert client.get("/api/correspondence").status_code == 200


def test_only_the_intended_routes_require_a_session():
    """A route gaining or losing the requirement must be a deliberate change here."""
    routes = route_helpers.api_routes(real_app)
    assert len(routes) > 50  # the walk reached the feature routers
    requiring = set()
    for route in routes:
        dependant = getattr(route, "dependant", None)
        calls = {d.call for d in dependant.dependencies} if dependant else set()
        if require_session in calls:
            requiring |= {(m, route.path) for m in route.methods}
    assert requiring == set(PROTECTED)
