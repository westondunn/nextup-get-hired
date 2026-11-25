"""Session-independent action logic, using only a synthetic store and mocked HTTP."""

import asyncio
from contextlib import nullcontext
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
from test_google_credentials import (
    BOTH,
    FALLBACK_ONLY,
    STORED_ONLY,
    client_only,
    connection,
    lifecycle,
)

from app import google_actions, google_lifecycle
from app.config import Settings
from app.models import GoogleConnection, GoogleLifecycle
from app.sources import gmail, google_calendar, google_oauth


@pytest.fixture
def store(monkeypatch):
    rows = {GoogleLifecycle: lifecycle(), GoogleConnection: connection()}
    session = MagicMock()
    session.get.side_effect = lambda model, key, **kwargs: rows[model]
    session.execute.return_value.one.side_effect = lambda: (
        rows[GoogleLifecycle],
        rows[GoogleConnection],
        None,
    )
    session.delete.side_effect = lambda row: rows.update({GoogleConnection: None})
    monkeypatch.setattr(google_lifecycle, "action", lambda _: nullcontext())
    monkeypatch.setattr(google_actions, "get_settings", lambda: STORED_ONLY)
    monkeypatch.setattr(
        google_actions, "_http_client", lambda: pytest.fail("Unexpected provider call")
    )
    return rows, session


def reply(monkeypatch, handler):
    monkeypatch.setattr(
        google_actions,
        "_http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def tokens(scope=None):
    return httpx.Response(
        200,
        json={
            "access_token": "mock-access",
            "scope": scope if scope is not None else f"{gmail.SCOPE} {google_calendar.SCOPE}",
        },
    )


def test_one_refresh_and_independent_probes(store, monkeypatch):
    rows, session = store
    before = rows[GoogleLifecycle].generation
    requests = []

    def handler(request):
        requests.append((request.method, str(request.url)))
        if request.url.path == "/token":
            return tokens()
        if request.url.path.endswith("/profile"):
            return httpx.Response(403, json={"error": {"errors": [{"reason": "domainPolicy"}]}})
        return httpx.Response(200, json={"id": "synthetic@example.test"})

    reply(monkeypatch, handler)
    result = google_actions.test_connection(session)
    assert result["result"] == "complete"
    assert result["capabilities"] == {"gmail": "admin_restricted", "calendar": "ok"}
    assert requests == [
        ("POST", google_oauth.TOKEN_URL),
        ("GET", f"{gmail.API_BASE}/profile"),
        ("GET", google_oauth.PRIMARY_CALENDAR_URL),
    ]
    assert rows[GoogleLifecycle].generation == before
    assert rows[GoogleLifecycle].calendar_last_success_at is None
    assert rows[GoogleConnection].state == "connected"
    session.commit.assert_not_called()


@pytest.mark.parametrize(
    "case,expected",
    [
        ("declined_scope", {"gmail": "wrong_scope", "calendar": "ok"}),
        ("disabled", {"gmail": "disabled", "calendar": "ok"}),
        ("not_granted", {"gmail": "not_granted", "calendar": "ok"}),
    ],
)
def test_only_eligible_scopes_are_probed(store, monkeypatch, case, expected):
    rows, session = store
    if case == "disabled":
        monkeypatch.setattr(
            google_actions,
            "get_settings",
            lambda: STORED_ONLY.model_copy(update={"gmail_sync_enabled": False}),
        )
    if case == "not_granted":
        rows[GoogleConnection].granted_scopes = [google_calendar.SCOPE]

    def handler(request):
        if request.method == "POST":
            return tokens(google_calendar.SCOPE)
        assert str(request.url) == google_oauth.PRIMARY_CALENDAR_URL
        return httpx.Response(200, json={"id": "synthetic@example.test"})

    reply(monkeypatch, handler)
    assert google_actions.test_connection(session)["capabilities"] == expected


@pytest.mark.parametrize(
    "status,count,code",
    [
        (429, 2, "temporarily_unavailable"),
        (503, 2, "temporarily_unavailable"),
        (403, 1, "provider_rejected"),
        (401, 1, "provider_rejected"),
    ],
)
def test_only_transient_reads_retry(store, monkeypatch, status, count, code):
    _, session = store
    calls = []

    def handler(request):
        calls.append(request.method)
        return tokens() if request.method == "POST" else httpx.Response(status)

    reply(monkeypatch, handler)
    result = google_actions.test_connection(session)
    assert result["capabilities"] == dict.fromkeys(("gmail", "calendar"), code)
    assert calls == ["POST"] + ["GET"] * (2 * count)


def test_slow_response_keeps_completed_probe_and_bounds_the_whole_action(store, monkeypatch):
    _, session = store
    calls = []

    async def handler(request):
        calls.append(request.method)
        if request.method == "POST":
            return tokens()
        if request.url.path.endswith("/profile"):
            return httpx.Response(200, json={"emailAddress": "synthetic@example.test"})
        await asyncio.sleep(2)
        pytest.fail("deadline did not interrupt the slow probe")

    monkeypatch.setattr(google_actions, "TEST_SECONDS", 0.05)
    reply(monkeypatch, handler)
    assert google_actions.test_connection(session)["capabilities"] == {
        "gmail": "ok",
        "calendar": "temporarily_unavailable",
    }
    assert calls == ["POST", "GET", "GET"]


@pytest.mark.parametrize(
    "row,settings,code",
    [
        (None, STORED_ONLY, "not_connected"),
        (
            None,
            FALLBACK_ONLY.model_copy(update={"token_key": STORED_ONLY.token_key}),
            "configured_externally",
        ),
        (client_only(), STORED_ONLY, "not_connected"),
        (connection(state="needs_reauthorization"), STORED_ONLY, "needs_reauthorization"),
        (connection(client_secret_sealed="unusable"), STORED_ONLY, "unreadable"),
        (connection(granted_scopes=[]), STORED_ONLY, "no_enabled_grant"),
        (connection(), Settings(), "switched_off"),
        (connection(), Settings(fixture_data_mode=True), "fixture_mode"),
        (connection(), Settings(gmail_sync_enabled=True), "no_key"),
    ],
)
def test_action_refusals_contact_nothing(store, monkeypatch, row, settings, code):
    rows, session = store
    rows[GoogleConnection] = row
    monkeypatch.setattr(google_actions, "get_settings", lambda: settings)
    with pytest.raises(HTTPException) as caught:
        google_actions.test_connection(session)
    assert (caught.value.status_code, caught.value.detail["code"]) == (409, code)


@pytest.mark.parametrize(
    "status,revocation", [(200, "confirmed"), (400, "unconfirmed"), (503, "unconfirmed")]
)
def test_local_removal_precedes_exactly_one_revocation_and_repeat_contacts_nothing(
    store, monkeypatch, status, revocation
):
    rows, session = store
    old_epoch = rows[GoogleLifecycle].epoch
    calls = []

    def handler(request):
        assert rows[GoogleConnection] is None and session.commit.called
        assert rows[GoogleLifecycle].sync_paused and rows[GoogleLifecycle].epoch != old_epoch
        assert request.method == "POST" and str(request.url) == google_oauth.REVOCATION_URL
        calls.append(1)
        return httpx.Response(status)

    reply(monkeypatch, handler)
    result = google_actions.disconnect(session)
    assert result["result"] == "disconnected" and result["revocation"] == revocation
    assert ("warning" in result) == (revocation == "unconfirmed")
    assert result["connection"]["credential_source"] == "none"
    again = google_actions.disconnect(session)
    assert (again["result"], again["revocation"]) == ("already_disconnected", "not_applicable")
    assert calls == [1]


@pytest.mark.parametrize(
    "settings",
    [BOTH, Settings(), Settings(fixture_data_mode=True), Settings(gmail_sync_enabled=True)],
)
def test_disconnect_preserves_fallback_and_never_contacts_google_when_unsafe(
    store, monkeypatch, settings
):
    rows, session = store
    monkeypatch.setattr(google_actions, "get_settings", lambda: settings)
    result = google_actions.disconnect(session)
    assert result["result"] == "disconnected" and result["revocation"] == "unconfirmed"
    assert "Google Account" in result["warning"]
    assert rows[GoogleConnection] is None and rows[GoogleLifecycle].sync_paused
    if settings is BOTH:
        assert result["connection"]["credential_source"] == "configured"
        with pytest.raises(HTTPException) as caught:
            google_actions.disconnect(session)
        assert caught.value.detail["code"] == "configured_externally"


def test_failed_local_commit_never_contacts_provider(store):
    _, session = store
    session.commit.side_effect = OperationalError("private", {}, RuntimeError("private"))
    with pytest.raises(HTTPException) as caught:
        google_actions.disconnect(session)
    assert (caught.value.status_code, caught.value.detail["code"]) == (503, "connection_error")
    assert "private" not in str(caught.value.detail)


def test_a_slow_revoke_cannot_undo_local_removal_or_claim_confirmation(store, monkeypatch):
    rows, session = store

    async def handler(request):
        assert rows[GoogleConnection] is None and session.commit.called
        await asyncio.sleep(2)
        pytest.fail("deadline did not interrupt revocation")

    monkeypatch.setattr(google_actions, "REVOKE_SECONDS", 0.03)
    reply(monkeypatch, handler)
    result = google_actions.disconnect(session)
    assert result["revocation"] == "unconfirmed"
    assert rows[GoogleLifecycle].sync_paused


@pytest.mark.parametrize(
    "http_status,body,expected,state",
    [
        (400, {"error": "invalid_grant"}, "needs_reauthorization", "needs_reauthorization"),
        (400, {"error": "admin_policy_enforced"}, "admin_restricted", "connected"),
        (
            400,
            {"error": "other", "error_description": "private-provider-value"},
            "provider_rejected",
            "connected",
        ),
        (429, {}, "temporarily_unavailable", "connected"),
        (503, {}, "temporarily_unavailable", "connected"),
        (
            200,
            {"access_token": "invalid\u2603", "scope": gmail.SCOPE + " " + google_calendar.SCOPE},
            "provider_rejected",
            "connected",
        ),
    ],
)
def test_refresh_refusals_are_safe_and_single_attempt(
    store, monkeypatch, http_status, body, expected, state
):
    from test_google_credentials import ShortSession

    rows, session = store
    short = ShortSession(rows[GoogleConnection])
    short.lifecycle = rows[GoogleLifecycle]
    monkeypatch.setattr(google_actions.google_credentials, "_connection_session", lambda _: short)
    requests = []

    def handler(request):
        requests.append(request.method)
        return httpx.Response(http_status, json=body)

    reply(monkeypatch, handler)
    response = google_actions.test_connection(session)
    assert requests == ["POST"]
    assert response["capabilities"] == {"gmail": expected, "calendar": expected}
    assert rows[GoogleConnection].state == state and response["connection"]["state"] == state
    assert "private-provider-value" not in str(response)
    assert all(
        status["last_attempt_at"] is None for status in response["connection"]["sync"].values()
    )


@pytest.mark.parametrize(
    "error,expected_attempts", [(httpx.ConnectError, 1), (httpx.ReadTimeout, 2)]
)
def test_only_a_probe_timeout_retries_after_a_transport_error(
    store, monkeypatch, error, expected_attempts
):
    rows, session = store
    rows[GoogleConnection].granted_scopes = [gmail.SCOPE]
    calls = []

    def handler(request):
        if request.method == "POST":
            return tokens()
        calls.append(1)
        raise error("private-provider-value")

    reply(monkeypatch, handler)
    response = google_actions.test_connection(session)
    assert response["capabilities"] == {
        "gmail": "temporarily_unavailable",
        "calendar": "not_granted",
    }
    assert len(calls) == expected_attempts
    assert "private-provider-value" not in str(response)


def test_client_only_removal_fences_earlier_flow_without_revoking(store):
    rows, session = store
    rows[GoogleConnection] = client_only()
    before = rows[GoogleLifecycle].epoch
    result = google_actions.disconnect(session)
    assert result["result"] == "disconnected" and result["revocation"] == "not_applicable"
    assert (
        rows[GoogleLifecycle].epoch != before and result["connection"]["state"] == "not_configured"
    )


def test_unreadable_stored_client_does_not_revoke_even_if_token_is_still_readable(store):
    rows, session = store
    rows[GoogleConnection].client_secret_sealed = "invalid"
    result = google_actions.disconnect(session)
    assert result["revocation"] == "unconfirmed" and rows[GoogleConnection] is None
