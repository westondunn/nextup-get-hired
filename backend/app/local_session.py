"""Local session for integration and credential routes.

Layer 3 of ``docs/decisions/0001-local-session-boundary.md``. The launcher writes a setup
code to the secrets directory. Presenting it once starts a session, carried in an
``HttpOnly`` cookie. Sessions live in Redis under a hash of their identifier, so the
identifier itself is never stored, and Redis key expiry enforces the idle limit.

Nothing here logs or returns the setup code or a session identifier.
"""

import hashlib
import hmac
import json
import logging
import secrets
import time
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from redis import Redis
from redis.exceptions import RedisError

from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/session", tags=["session"])

COOKIE_NAME = "nextup_session"
COOKIE_PATH = "/api"
IDLE_SECONDS = 12 * 60 * 60
MAX_SECONDS = 7 * 24 * 60 * 60
KEY_PREFIX = "nextup:session:"
# The launcher generates far longer codes; anything shorter is treated as not configured.
MIN_SETUP_CODE_LENGTH = 24
FAILURE_DELAY_SECONDS = 0.5

SESSION_REQUIRED = "A local session is required."
SESSION_REFUSED = "Session refused."
NOT_CONFIGURED = "Local sessions are not configured."
STORE_UNAVAILABLE = "Session store unavailable."
INVALID_REQUEST = "Invalid session request."
MAX_BODY_BYTES = 2048
MAX_CODE_LENGTH = 512


class SessionStore:
    """Sessions keyed by a hash of their identifier; the value is the absolute deadline."""

    def __init__(self, client) -> None:
        self._client = client

    @staticmethod
    def _key(identifier: str) -> str:
        return KEY_PREFIX + hashlib.sha256(identifier.encode()).hexdigest()

    def create(self, now: float) -> str:
        identifier = secrets.token_urlsafe(32)
        self._client.set(self._key(identifier), str(int(now) + MAX_SECONDS), ex=IDLE_SECONDS)
        return identifier

    def touch(self, identifier: str, now: float) -> bool:
        """Whether the session is live. A live session's idle limit starts again."""
        key = self._key(identifier)
        raw = self._client.get(key)
        if raw is None:
            return False
        try:
            remaining = int(raw) - int(now)
        except ValueError:
            remaining = 0
        if remaining <= 0:
            self._client.delete(key)
            return False
        self._client.expire(key, min(IDLE_SECONDS, remaining))
        return True

    def end(self, identifier: str) -> None:
        self._client.delete(self._key(identifier))


@lru_cache
def _redis_client() -> Redis:
    return Redis.from_url(get_settings().redis_url, socket_connect_timeout=3, socket_timeout=3)


def get_store() -> SessionStore:
    return SessionStore(_redis_client())


Store = Annotated[SessionStore, Depends(get_store)]


def _setup_code() -> str | None:
    value = get_settings().setup_code.get_secret_value()
    return value if len(value) >= MIN_SETUP_CODE_LENGTH else None


def _unavailable() -> HTTPException:
    logger.warning("Session store unavailable")
    return HTTPException(503, STORE_UNAVAILABLE)


def _is_active(request: Request, store: SessionStore) -> bool:
    identifier = request.cookies.get(COOKIE_NAME)
    if not identifier:
        return False
    try:
        return store.touch(identifier, time.time())
    except RedisError:
        raise _unavailable() from None


def require_session(request: Request, store: Store) -> None:
    """Route dependency: refuse with 401 unless the request carries a live session."""
    if not _is_active(request, store):
        raise HTTPException(401, SESSION_REQUIRED)


async def _submitted_code(request: Request) -> str:
    """The ``code`` of a ``{"code": "..."}`` body.

    Parsed by hand: the framework's own validation errors repeat the submitted body, and
    a mistyped request may contain the setup code.
    """
    body = await request.body()
    try:
        if len(body) > MAX_BODY_BYTES:
            raise ValueError
        payload = json.loads(body)
        code = payload["code"]
        if set(payload) != {"code"} or not isinstance(code, str):
            raise ValueError
        if not 0 < len(code) <= MAX_CODE_LENGTH:
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise HTTPException(422, INVALID_REQUEST) from None
    return code


@router.get("")
def read_session(request: Request, store: Store):
    return {"configured": _setup_code() is not None, "active": _is_active(request, store)}


@router.post("", status_code=204)
def start_session(code: Annotated[str, Depends(_submitted_code)], response: Response, store: Store):
    expected = _setup_code()
    if expected is None:
        raise HTTPException(503, NOT_CONFIGURED)
    if not hmac.compare_digest(code.encode(), expected.encode()):
        time.sleep(FAILURE_DELAY_SECONDS)
        logger.warning("Session refused")
        raise HTTPException(401, SESSION_REFUSED)
    try:
        identifier = store.create(time.time())
    except RedisError:
        raise _unavailable() from None
    # No Secure attribute: the application is served over plain HTTP on loopback only.
    response.set_cookie(
        COOKIE_NAME,
        identifier,
        max_age=MAX_SECONDS,
        path=COOKIE_PATH,
        httponly=True,
        samesite="strict",
    )


@router.delete("", status_code=204)
def end_session(request: Request, response: Response, store: Store):
    identifier = request.cookies.get(COOKIE_NAME)
    if identifier:
        try:
            store.end(identifier)
        except RedisError:
            raise _unavailable() from None
    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH, httponly=True, samesite="strict")
