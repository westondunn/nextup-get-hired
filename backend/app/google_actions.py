"""Session-protected checks and local-first removal of the saved Google connection."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager, suppress

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import google_connection, google_credentials, google_lifecycle, token_vault
from app.config import Settings, get_settings
from app.google_connection import Database
from app.local_session import require_session
from app.models import GoogleConnection
from app.sources import gmail, google_oauth
from app.sources.common import SourceError, require_live_requests

router = APIRouter(prefix="/api/google", tags=["google"], dependencies=[Depends(require_session)])
TEST_SECONDS = 10.0
REVOKE_SECONDS = 5.0
WARNING = (
    "Removal at Google could not be confirmed. You can check or remove access under "
    "third-party access in your Google Account. Removing a shared grant can affect other "
    "credentials."
)
MESSAGES = {
    "fixture_mode": "Google connection tests are unavailable in sample data mode.",
    "switched_off": "Google connections are switched off in this installation.",
    "no_key": "The key for the saved Google connection is unavailable.",
    "not_connected": "No saved Google grant is connected.",
    "configured_externally": "Google credentials are managed in the installation configuration.",
    "unreadable": "The saved Google connection cannot be read with this key.",
    "needs_reauthorization": google_credentials.NEEDS_REAUTHORIZATION,
    "busy": google_lifecycle.BUSY_MESSAGE,
    "no_enabled_grant": "No enabled Google capability is included in the saved grant.",
    "connection_error": "The local Google connection could not be read or updated.",
}


def _refusal(code: str) -> HTTPException:
    return HTTPException(
        503 if code == "connection_error" else 409, {"code": code, "message": MESSAGES[code]}
    )


@contextmanager
def _action(session: Session) -> Iterator[None]:
    try:
        with google_lifecycle.action(session):
            yield
    except google_lifecycle.LifecycleBusy:
        raise _refusal("busy") from None
    except SourceError as error:
        if error.code == "connection_not_updated":
            raise _refusal("connection_error") from None
        raise
    except SQLAlchemyError:
        with suppress(SQLAlchemyError):
            session.rollback()
        raise _refusal("connection_error") from None


def _http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=3.0, follow_redirects=False, trust_env=False)


async def _read(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
    # Both a total deadline (at the action) and a byte cap apply to a slow/oversized response.
    async with client.stream(method, url, **kwargs) as response:
        if response.status_code == 429 or 500 <= response.status_code < 600:
            return httpx.Response(response.status_code)
        content = bytearray()
        async for chunk in response.aiter_bytes():
            if len(content) + len(chunk) > google_oauth.MAX_RESPONSE_BYTES:
                raise SourceError("too_large", "Google returned an oversized response.")
            content.extend(chunk)
        return httpx.Response(response.status_code, content=bytes(content))


def _probe_code(error: SourceError) -> str:
    if error.code in ("wrong_scope", "needs_reauthorization", "admin_restricted"):
        return error.code
    if error.code in ("provider_unavailable", "network_error"):
        return "temporarily_unavailable"
    if error.code == "connection_not_updated":
        raise _refusal("connection_error")
    return "provider_rejected"


async def _probe(client: httpx.AsyncClient, name: str, token: str, deadline: float) -> str:
    url, field = google_oauth.ACCOUNT_LOOKUPS[name]
    for attempt in range(2):
        if asyncio.get_running_loop().time() >= deadline:
            return "temporarily_unavailable"
        try:
            response = await _read(client, "GET", url, headers={"Authorization": f"Bearer {token}"})
            if not attempt and (response.status_code == 429 or 500 <= response.status_code < 600):
                continue
            payload = gmail.response_json(response)
            google_oauth.account_address(payload, field)
            return "ok"
        except httpx.TimeoutException:
            if attempt:
                return "temporarily_unavailable"
        except httpx.RequestError:
            return "temporarily_unavailable"
        except SourceError as error:
            return _probe_code(error)
    return "temporarily_unavailable"


async def _test_grant(
    session: Session,
    settings: Settings,
    credentials: google_credentials.Credentials,
    applicable: list[str],
    results: dict[str, str],
) -> None:
    require_live_requests(settings)
    deadline = asyncio.get_running_loop().time() + TEST_SECONDS
    try:
        async with asyncio.timeout_at(deadline), _http_client() as client:
            form = gmail.refresh_form(
                credentials.client_id, credentials.client_secret, credentials.refresh_token
            )
            try:
                response = await _read(client, "POST", google_oauth.TOKEN_URL, data=form)
                payload = gmail.response_json(response, refresh=True)
                google_credentials.keep_new_refresh_token(session, settings, credentials, payload)
            except SourceError as error:
                failure = google_credentials.refresh_refusal(session, settings, credentials, error)
                for name in applicable:
                    results[name] = _probe_code(failure)
                return
            for name in applicable:
                try:
                    token = google_credentials.CHECKED[name](payload)
                except SourceError as error:
                    results[name] = _probe_code(error)
                    continue
                if not google_oauth.TOKEN.fullmatch(token):
                    results[name] = "provider_rejected"
                    continue
                results[name] = await _probe(client, name, token, deadline)
    except (TimeoutError, httpx.RequestError):
        # Untested capabilities started with this outcome. Keep any completed earlier probe.
        return


@router.post("/connection/test")
def test_connection(session: Database):
    settings = get_settings()
    with _action(session):
        status = google_connection.connection_status(session, settings)
        if reason := status["unavailable_reason"]:
            raise _refusal(reason)
        if status["credential_source"] == "configured":
            raise _refusal("configured_externally")
        if status["credential_source"] != "stored":
            raise _refusal("not_connected")
        if status["state"] in ("unreadable", "needs_reauthorization"):
            raise _refusal(status["state"])
        applicable = []
        results = {}
        for name in google_oauth.CAPABILITY_SCOPES:
            if name not in status["enabled_capabilities"]:
                results[name] = "disabled"
            elif name not in status["granted_capabilities"]:
                results[name] = "not_granted"
            else:
                applicable.append(name)
                results[name] = "temporarily_unavailable"
        if not applicable:
            raise _refusal("no_enabled_grant")
        try:
            credentials = google_credentials.resolve(session, settings, applicable[0])
        except SourceError as error:
            code = {
                "connection_unreadable": "unreadable",
                "not_connected": "not_connected",
                "needs_reauthorization": "needs_reauthorization",
            }.get(error.code, "connection_error")
            raise _refusal(code) from None
        session.rollback()  # Release the read transaction before contacting the provider.
        asyncio.run(_test_grant(session, settings, credentials, applicable, results))
        return {
            "result": "complete",
            "capabilities": results,
            "connection": google_connection.connection_status(session, settings),
        }


async def _revoke(settings: Settings, token: str) -> bool:
    require_live_requests(settings)
    try:
        async with asyncio.timeout(REVOKE_SECONDS), _http_client() as client:
            async with client.stream(
                "POST", google_oauth.REVOCATION_URL, data={"token": token}
            ) as response:
                return response.status_code == 200
    except (TimeoutError, httpx.RequestError):
        return False


@router.delete("/connection")
def disconnect(session: Database):
    settings = get_settings()
    with _action(session):
        lifecycle = google_lifecycle.lifecycle_row(session, lock=True)
        row = session.get(GoogleConnection, 1, with_for_update=True, populate_existing=True)
        fallback = gmail.credentials_present(settings)
        if row is None and fallback:
            raise _refusal("configured_externally")
        result, revocation, token = "already_disconnected", "not_applicable", None
        if row is not None:
            result = "disconnected"
            if row.refresh_token_sealed is not None:
                revocation = "unconfirmed"
                if not fallback and google_connection.unavailable_reason(settings) is None:
                    try:
                        token_vault.open_sealed(
                            row.client_secret_sealed,
                            purpose=google_connection.CLIENT_SECRET_PURPOSE,
                            settings=settings,
                        )
                        token = token_vault.open_sealed(
                            row.refresh_token_sealed,
                            purpose=google_connection.REFRESH_TOKEN_PURPOSE,
                            settings=settings,
                        )
                    except token_vault.VaultError:
                        pass
            session.delete(row)
            google_lifecycle.invalidate(lifecycle)
        session.flush()
        status = google_connection.connection_status(session, settings)
        session.commit()
        if token and asyncio.run(_revoke(settings, token)):
            revocation = "confirmed"
        response = {"result": result, "revocation": revocation, "connection": status}
        if revocation == "unconfirmed":
            response["warning"] = WARNING
        return response
