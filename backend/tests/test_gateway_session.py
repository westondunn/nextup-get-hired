"""Session cookies and Google consent on the authenticated staging entrypoint."""

from http.cookies import SimpleCookie
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from test_gateway import EXTERNAL_ORIGIN, HEADER, issued
from test_gateway import key as key
from test_gateway import origin_app as origin_app
from test_gateway import policy_text as policy_text
from test_local_session import CODE

from app import google_consent, local_session, main
from app.db import get_session


@pytest.fixture
def client(origin_app, key):
    return TestClient(
        origin_app(EXTERNAL_ORIGIN),
        base_url=EXTERNAL_ORIGIN,
        headers={HEADER: issued(key), "Origin": EXTERNAL_ORIGIN},
        follow_redirects=False,
    )


def test_setup_and_logout_use_secure_host_only_cookies(client, monkeypatch):
    store = Mock(spec=local_session.SessionStore)
    store.create.return_value = "synthetic-session-identifier"
    monkeypatch.setitem(main.app.dependency_overrides, local_session.get_store, lambda: store)
    monkeypatch.setattr(local_session, "_setup_code", lambda: CODE)

    started = client.post("/api/session", json={"code": CODE})
    assert started.status_code == 204
    ended = client.delete("/api/session")
    assert ended.status_code == 204
    store.end.assert_called_once_with(store.create.return_value)

    for response, max_age in [(started, local_session.MAX_SECONDS), (ended, 0)]:
        cookie = SimpleCookie(response.headers["set-cookie"])[local_session.COOKIE_NAME]
        assert cookie["secure"] and cookie["httponly"] and not cookie["domain"]
        assert cookie["samesite"].lower() == "strict" and cookie["path"] == "/api"
        assert cookie["max-age"] == str(max_age)


@pytest.mark.parametrize("suffix", ["", "/"])
@pytest.mark.parametrize(
    ("method", "path"), [("POST", "/api/google/connect"), ("GET", "/api/google/callback")]
)
def test_external_consent_is_unavailable_before_route_dependencies(
    client, monkeypatch, method, path, suffix
):
    def unexpected():
        pytest.fail("External consent reached a route dependency or provider")

    for dependency in (get_session, local_session.get_store, google_consent.get_flow_store):
        monkeypatch.setitem(main.app.dependency_overrides, dependency, unexpected)
    monkeypatch.setattr(google_consent, "_http_client", unexpected)
    response = client.request(method, path + suffix)
    assert response.status_code == 404 and response.json() == {"detail": "Not Found"}
    assert "set-cookie" not in response.headers and "location" not in response.headers
