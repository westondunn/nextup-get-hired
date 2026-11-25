"""The Google consent flow: starting it, and the callback that stores the grant.

See docs/decisions/0003-google-connection.md, sections 3 to 5. The start route needs a
local session. The callback cannot: the session cookie is ``SameSite=Strict``, and a
browser does not send it on the navigation that arrives from Google. The callback is tied
to the session that started the flow by a single-use ``state`` entry and a browser-binding
cookie instead.

No token, secret, code, verifier, ``state`` or binding value is logged or placed in a
response body, and no error repeats what Google or the browser sent. The two log lines in
this module carry an exception type or one of this application's own failure codes, and
nothing else.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import re
import secrets
from contextlib import suppress
from datetime import UTC, datetime
from time import monotonic
from typing import Annotated
from urllib.parse import parse_qs

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import google_lifecycle, token_vault
from app.config import Settings, get_settings
from app.db import get_session
from app.google_connection import (
    CLIENT_SECRET_PURPOSE,
    KEY_VERSION,
    REFRESH_TOKEN_PURPOSE,
    require_available,
)
from app.local_session import STORE_UNAVAILABLE, _redis_client, require_session
from app.models import GoogleConnection
from app.request_boundary import LOCAL_HOSTS, host_name
from app.sources import gmail, google_oauth
from app.sources.common import SourceError
from app.sources.google_oauth import CAPABILITY_SCOPES

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/google", tags=["google"])
Database = Annotated[Session, Depends(get_session)]

CALLBACK_PATH = "/api/google/callback"
FLOW_SECONDS = 10 * 60
CONSENT_PROVIDER_SECONDS = 10
FLOW_KEY_PREFIX = "nextup:google:flow:"
# One cookie per flow, named after a hash of its state, so two flows in one browser do not
# overwrite each other.
BINDING_COOKIE_PREFIX = "nextup_google_flow_"
MAX_BODY_BYTES = 256
# ``secrets.token_urlsafe(32)``: 256 bits, 43 characters.
STATE = re.compile(r"[A-Za-z0-9_-]{43}")
CODE = re.compile(r"[\x21-\x7e]{1,2048}")

# The callback answers with a redirect to this address and one of these words, nothing else.
RESULT_ADDRESS = "/?google="
RESULTS = frozenset(
    {
        "connected",
        # Connected, but the grant of the account connected before could not be revoked.
        "connected_earlier_not_revoked",
        "declined",
        "not_granted",
        "failed",
    }
)
FLOW_HEADERS = {"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"}

INVALID_CAPABILITIES = "Choose Gmail, Calendar or both to connect."
CAPABILITY_OFF = (
    "A requested capability is switched off in this installation's configuration, so it "
    "cannot be connected."
)
HOST_NOT_LOCAL = "Open NextUp as localhost or 127.0.0.1 to connect a Google account."
NO_CLIENT = "Save a Google client before connecting an account."
CLIENT_UNREADABLE = (
    "The stored Google client cannot be read with the current encryption key. Save the "
    "client again."
)
FLOW_REFUSED = "This connection attempt is not valid or has expired. Start again from Settings."


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _cookie_name(state: str) -> str:
    return BINDING_COOKIE_PREFIX + _digest(state)[:16]


class FlowStore:
    """Pending flows, keyed by a hash of ``state``. An entry lasts ten minutes and one read."""

    def __init__(self, client) -> None:
        self._client = client

    @staticmethod
    def _key(state: str) -> str:
        return FLOW_KEY_PREFIX + _digest(state)

    def put(self, state: str, entry: dict) -> None:
        self._client.set(self._key(state), json.dumps(entry), ex=FLOW_SECONDS)

    def take(self, state: str) -> dict | None:
        """The entry, deleted in the same step, so a second read finds nothing."""
        raw = self._client.getdel(self._key(state))
        if raw is None:
            return None
        try:
            entry = json.loads(raw)
        except ValueError:
            return None
        return entry if isinstance(entry, dict) else None


def get_flow_store() -> FlowStore:
    return FlowStore(_redis_client())


Flows = Annotated[FlowStore, Depends(get_flow_store)]


class _ConsentTransport(httpx.BaseTransport):
    """One deadline across the callback's sync adapter calls, including streamed bodies."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.runner = asyncio.Runner()
        self.deadline = monotonic() + CONSENT_PROVIDER_SECONDS

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        try:
            return self.runner.run(self._send(request))
        except TimeoutError:
            raise httpx.ReadTimeout(
                "Google consent exceeded its time limit.", request=request
            ) from None

    async def _send(self, request: httpx.Request) -> httpx.Response:
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError
        async with asyncio.timeout(remaining):
            response = await self.client.send(request, stream=True)
            try:
                # These callers need only the status on rejection or revocation.
                if response.status_code != 200 or request.url == google_oauth.REVOCATION_URL:
                    return httpx.Response(response.status_code)
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise SourceError("invalid_response", "Google returned an unexpected encoding.")
                limit = (
                    google_oauth.MAX_RESPONSE_BYTES
                    if request.url == google_oauth.TOKEN_URL
                    else gmail.MAX_RESPONSE_BYTES
                )
                content = bytearray()
                async for part in response.aiter_bytes(chunk_size=8192):
                    if len(content) + len(part) > limit:
                        raise SourceError(
                            "invalid_response", "Google response exceeded its size limit."
                        )
                    content.extend(part)
                return httpx.Response(response.status_code, content=bytes(content))
            finally:
                await response.aclose()

    def close(self) -> None:
        with self.runner:
            self.runner.run(self.client.aclose())


def _async_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(follow_redirects=False, trust_env=False)


def _http_client() -> httpx.Client:
    return httpx.Client(
        transport=_ConsentTransport(_async_http_client()),
        headers={"Accept-Encoding": "identity"},
        follow_redirects=False,
        trust_env=False,
    )


async def _requested_capabilities(request: Request) -> tuple[str, ...]:
    """The ``capability`` fields of the submitted form. Parsed by hand, so no error echoes it."""
    body = await request.body()
    try:
        if len(body) > MAX_BODY_BYTES:
            raise ValueError
        fields = parse_qs(
            body.decode("ascii"),
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=len(CAPABILITY_SCOPES),
        )
        requested = fields.get("capability", [])
        if set(fields) != {"capability"} or len(set(requested)) != len(requested):
            raise ValueError
        if not set(requested) <= set(CAPABILITY_SCOPES):
            raise ValueError
    except ValueError:
        raise HTTPException(422, INVALID_CAPABILITIES) from None
    return tuple(name for name in CAPABILITY_SCOPES if name in requested)


def _capability_enabled(settings: Settings, capability: str) -> bool:
    if capability == "gmail":
        return settings.gmail_sync_enabled
    return settings.calendar_sync_enabled


def _redirect_address(request: Request) -> str:
    """The callback address for the host this request was made to.

    The ``Host`` header has passed the request boundary's allowlist. Only the two loopback
    names are used here, which are also the only plain-HTTP addresses Google accepts.
    """
    authority = request.headers.get("host", "").strip().lower()
    if host_name(authority) not in LOCAL_HOSTS:
        raise HTTPException(400, HOST_NOT_LOCAL)
    return f"http://{authority}{CALLBACK_PATH}"


@router.post("/connect", dependencies=[Depends(require_session)])
def start_connection(
    request: Request,
    capabilities: Annotated[tuple[str, ...], Depends(_requested_capabilities)],
    session: Database,
    flows: Flows,
):
    """Answer a submitted form with a redirect to Google's consent screen."""
    settings = get_settings()
    require_available(settings)
    if not all(_capability_enabled(settings, name) for name in capabilities):
        raise HTTPException(409, CAPABILITY_OFF)
    redirect_address = _redirect_address(request)
    lifecycle = google_lifecycle.lifecycle_row(session, lock=True)
    row = session.get(GoogleConnection, 1, populate_existing=True)
    if row is None:
        raise HTTPException(409, NO_CLIENT)
    try:
        token_vault.open_sealed(
            row.client_secret_sealed, purpose=CLIENT_SECRET_PURPOSE, settings=settings
        )
    except token_vault.VaultError:
        raise HTTPException(409, CLIENT_UNREADABLE) from None
    client_id = row.client_id
    epoch = str(lifecycle.epoch)
    session.rollback()  # Release the local fence before contacting Redis.
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    binding = secrets.token_urlsafe(32)
    try:
        flows.put(
            state,
            {
                "verifier": verifier,
                "redirect_address": redirect_address,
                "capabilities": list(capabilities),
                "binding": _digest(binding),
                "client_id": client_id,
                "epoch": epoch,
            },
        )
    except RedisError:
        raise HTTPException(503, STORE_UNAVAILABLE) from None
    response = RedirectResponse(
        google_oauth.authorization_url(
            client_id=client_id,
            redirect_uri=redirect_address,
            capabilities=capabilities,
            state=state,
            verifier=verifier,
        ),
        status_code=303,
        headers=FLOW_HEADERS,
    )
    # No Secure attribute: the application is served over plain HTTP on loopback only.
    response.set_cookie(
        _cookie_name(state),
        binding,
        max_age=FLOW_SECONDS,
        path=CALLBACK_PATH,
        httponly=True,
        samesite="lax",
    )
    return response


def _single(request: Request, name: str) -> str | None:
    values = request.query_params.getlist(name)
    return values[0] if len(values) == 1 else None


def _result(word: str, cookie_name: str) -> Response:
    assert word in RESULTS
    response = RedirectResponse(RESULT_ADDRESS + word, status_code=303)
    response.delete_cookie(cookie_name, path=CALLBACK_PATH, httponly=True, samesite="lax")
    return response


def _store(
    session: Session,
    settings: Settings,
    entry: dict,
    grant: google_oauth.Grant,
    addresses: tuple[str, ...],
) -> tuple[bool, bool, str | None]:
    """Store the grant under the row lock.

    Returns whether it was stored, whether it replaced the grant of a different account,
    and that earlier grant's refresh token when it can be revoked. Nothing is sent to
    Google here, so the lock is never held across a network call.
    """
    # Every change to the connection takes this row lock (decision 0003, section 7). The
    # row is read again from the database, whatever this session loaded before.
    lifecycle = google_lifecycle.lifecycle_row(session, lock=True)
    row = session.get(GoogleConnection, 1, with_for_update=True, populate_existing=True)
    if (
        row is None
        or row.client_id != entry["client_id"]
        or str(lifecycle.epoch) != entry.get("epoch")
    ):
        # The client was replaced while the user was at Google. The grant belongs to the
        # earlier client and is discarded.
        session.rollback()
        return False, False, None
    replaced_other, earlier = False, None
    if row.refresh_token_sealed is not None:
        known = (row.account_address or "").lower()
        # The same account keeps its grant at Google: revoking the earlier token would
        # end the new one as well. An earlier grant whose account is not known is left
        # alone for the same reason.
        if known not in addresses:
            replaced_other = True
            # Configuration credentials may share the old grant. Their ownership is
            # not established here, so leave any remote revocation to the user.
            if known and not gmail.credentials_present(settings):
                try:
                    earlier = token_vault.open_sealed(
                        row.refresh_token_sealed, purpose=REFRESH_TOKEN_PURPOSE, settings=settings
                    )
                except token_vault.VaultError:
                    pass
    now = datetime.now(UTC)
    row.refresh_token_sealed = token_vault.seal(
        grant.refresh_token, purpose=REFRESH_TOKEN_PURPOSE, settings=settings
    )
    row.key_version = KEY_VERSION
    row.state = "connected"
    row.granted_scopes = sorted(grant.scopes)
    row.account_address = addresses[0]
    row.connected_at = now
    row.updated_at = now
    google_lifecycle.advance_generation(lifecycle)
    session.commit()
    return True, replaced_other, earlier


def _revoked(client: httpx.Client, settings: Settings, token: str) -> bool:
    try:
        return google_oauth.revoke(client, settings, token)
    except Exception:  # noqa: BLE001 - a failed revocation never changes what was stored
        return False


def _complete(request: Request, session: Session, settings: Settings, entry: dict) -> str:
    """Finish a flow whose ``state`` and binding checks have passed. Returns the result word."""
    errors = request.query_params.getlist("error")
    if errors:
        # Google's own error text is neither shown nor logged.
        return "declined" if errors == ["access_denied"] else "failed"
    code = _single(request, "code")
    if code is None or not CODE.fullmatch(code):
        return "failed"
    lifecycle = google_lifecycle.lifecycle_row(session)
    row = session.get(GoogleConnection, 1, populate_existing=True)
    if (
        row is None
        or row.client_id != entry["client_id"]
        or str(lifecycle.epoch) != entry.get("epoch")
    ):
        return "failed"
    client_id = row.client_id
    # Whether NextUp holds a grant that a revocation at Google could end.
    grant_in_use = row.refresh_token_sealed is not None or gmail.credentials_present(settings)
    try:
        client_secret = token_vault.open_sealed(
            row.client_secret_sealed, purpose=CLIENT_SECRET_PURPOSE, settings=settings
        )
    except token_vault.VaultError:
        return "failed"
    session.rollback()  # no transaction stays open while Google is contacted
    try:
        with _http_client() as client:
            grant = google_oauth.exchange_code(
                client,
                settings,
                client_id=client_id,
                client_secret=client_secret,
                code=code,
                verifier=entry["verifier"],
                redirect_uri=entry["redirect_address"],
            )
            if not set(grant.capabilities()) & set(entry["capabilities"]):
                # Nothing that was asked for was granted, so nothing is stored. Google's
                # revocation ends an account's whole grant to this client, so the returned
                # token is revoked only when NextUp holds no grant that could be the same.
                if not grant_in_use:
                    _revoked(client, settings, grant.refresh_token or grant.access_token)
                return "not_granted"
            if not grant.refresh_token:
                return "failed"
            addresses = google_oauth.account_addresses(client, settings, grant)
            stored, replaced_other, earlier = _store(session, settings, entry, grant, addresses)
            if not stored:
                return "failed"
            # The grant of a different account is revoked once the new one is stored, so a
            # failure before this point leaves the earlier connection as it was.
            if replaced_other and not (earlier and _revoked(client, settings, earlier)):
                return "connected_earlier_not_revoked"
            return "connected"
    except SourceError as error:
        # The code is one of this application's own fixed words, never Google's text.
        logger.warning("Google connection not completed (%s)", error.code)
        return "failed"


def _finish(request: Request, session: Session, flows: FlowStore, settings: Settings) -> Response:
    require_available(settings)
    state = _single(request, "state")
    if state is None or not STATE.fullmatch(state):
        raise HTTPException(400, FLOW_REFUSED)
    # Acquire before spending state so a temporarily busy callback can be retried.
    try:
        with google_lifecycle.action(session):
            return _finish_held(request, session, flows, settings, state)
    except google_lifecycle.LifecycleBusy:
        raise HTTPException(409, google_lifecycle.BUSY_MESSAGE) from None
    except SQLAlchemyError:
        raise HTTPException(503, STORE_UNAVAILABLE) from None


def _finish_held(
    request: Request, session: Session, flows: FlowStore, settings: Settings, state: str
) -> Response:
    try:
        entry = flows.take(state)
    except RedisError:
        raise HTTPException(503, STORE_UNAVAILABLE) from None
    cookie_name = _cookie_name(state)
    binding = request.cookies.get(cookie_name, "")
    if entry is None or not hmac.compare_digest(_digest(binding), str(entry.get("binding"))):
        raise HTTPException(400, FLOW_REFUSED)
    # From here the flow is the one this browser started, and every outcome is a result
    # word. The state is spent, so nothing is retried.
    try:
        word = _complete(request, session, settings, entry)
    except Exception as error:  # noqa: BLE001 - only the type of the error may be logged
        logger.warning("Google connection callback failed (%s)", type(error).__name__)
        with suppress(Exception):
            session.rollback()
        word = "failed"
    return _result(word, cookie_name)


@router.get("/callback")
def finish_connection(request: Request, session: Database, flows: Flows):
    """Where Google sends the browser back. Requires no session cookie; see the module text."""
    try:
        response = _finish(request, session, flows, get_settings())
    except HTTPException as refusal:
        response = JSONResponse({"detail": refusal.detail}, status_code=refusal.status_code)
    response.headers.update(FLOW_HEADERS)
    return response


class CallbackQueryFilter(logging.Filter):
    """Keeps the callback's query string out of the server's access log.

    The query string carries the authorization code and ``state``. Uvicorn's access record
    holds the request target as one argument; this cuts that argument at the ``?`` for the
    callback path, and drops the record altogether if it still shows a query string.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                arg.partition("?")[0]
                if isinstance(arg, str) and arg.startswith(CALLBACK_PATH)
                else arg
                for arg in record.args
            )
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a record that cannot be rendered is not written
            return False
        return CALLBACK_PATH not in message or "?" not in message.partition(CALLBACK_PATH)[2]


_access_log_filter = CallbackQueryFilter()


def protect_access_log() -> None:
    """Install the filter on Uvicorn's access logger. Safe to call more than once."""
    access = logging.getLogger("uvicorn.access")
    if _access_log_filter not in access.filters:
        access.addFilter(_access_log_filter)
