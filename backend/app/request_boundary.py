"""Local request boundary: host allowlist and cross-origin refusal.

Implements layers 1 and 2 of ``docs/decisions/0001-local-session-boundary.md``.

In the default deployment, layer 1 allows local Host names. This prevents DNS
rebinding, where a remote site points its own name at the loopback address.

Layer 2 refuses state-changing requests that a browser reports as coming from another
origin. The default deployment permits writes without browser origin metadata.

The normal app always uses its local host list. The staging gateway can supply one
operator-configured HTTPS origin in the ASGI scope after verifying an assertion.
Refusals and log lines never repeat a header value.
"""

import logging
from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.routing import get_route_path
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import get_settings
from app.gateway_origin import GatewayOrigin

logger = logging.getLogger(__name__)

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})
# Compose service names, used by the disposable CI stack only.
STACK_HOSTS = frozenset({"api", "frontend"})
STACK_ENVIRONMENTS = frozenset({"ci", "test"})
# Empty outside the test suite; tests/conftest.py adds the test client's host name.
TEST_HOSTS: frozenset[str] = frozenset()

STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
SAME_ORIGIN_FETCH_SITES = frozenset({"same-origin", "none"})

HOST_REFUSED = "Request refused: host not allowed."
CROSS_ORIGIN_REFUSED = "Request refused: cross-origin request."
GATEWAY_ORIGIN_SCOPE_KEY = "nextup.authenticated_gateway_origin"
LOCAL_CONSENT_PATHS = frozenset({"/api/google/connect", "/api/google/callback"})


def _environment() -> str:
    return get_settings().identity.environment


def allowed_hosts(environment: str) -> frozenset[str]:
    if environment in STACK_ENVIRONMENTS:
        return LOCAL_HOSTS | STACK_HOSTS | TEST_HOSTS
    return LOCAL_HOSTS | TEST_HOSTS


def host_name(authority: str) -> str | None:
    """The name part of a ``Host`` value, or None when it is not ``name[:port]``."""
    name, separator, port = authority.partition(":")
    if separator and not (port.isascii() and port.isdigit()):
        return None  # includes bracketed IPv6 literals and repeated colons
    return name or None


def _header_values(scope: Scope, name: bytes) -> list[str]:
    return [value.decode("latin-1") for key, value in scope["headers"] if key == name]


def _single(values: list[str]) -> str | None:
    return values[0].strip().lower() if len(values) == 1 else None


def is_cross_origin(
    fetch_sites: list[str],
    origins: list[str],
    authority: str,
    gateway_origin: GatewayOrigin | None = None,
) -> bool:
    """Whether browser-supplied headers show the request came from another origin."""
    if fetch_sites and _single(fetch_sites) not in SAME_ORIGIN_FETCH_SITES:
        return True
    if gateway_origin is not None:
        return len(origins) != 1 or not gateway_origin.matches_origin(origins[0])
    if origins:
        origin = _single(origins)
        if origin is None or urlsplit(origin).netloc != authority:
            return True
    return False


class RequestBoundaryMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # The API serves HTTP only; lifespan events pass through untouched.
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        hosts = _header_values(scope, b"host")
        authority = _single(hosts)
        gateway_origin: GatewayOrigin | None = scope.get(GATEWAY_ORIGIN_SCOPE_KEY)
        if gateway_origin is None:
            host_allowed = authority is not None and host_name(authority) in allowed_hosts(
                _environment()
            )
        else:
            host_allowed = len(hosts) == 1 and gateway_origin.matches_authority(hosts[0])
        if not host_allowed:
            logger.warning("Request refused: host not allowed")
            await JSONResponse({"detail": HOST_REFUSED}, status_code=400)(scope, receive, send)
            return
        if gateway_origin is not None:
            # Block the local-only OAuth flow before the router can issue a slash redirect.
            if get_route_path(scope).rstrip("/") in LOCAL_CONSENT_PATHS:
                await JSONResponse({"detail": "Not Found"}, status_code=404)(scope, receive, send)
                return
            # The upstream connection can be plain HTTP. Build browser URLs using the
            # verified policy and Host, independently of client-supplied proxy headers.
            scope = {**scope, "scheme": "https"}
        if scope["method"] in STATE_CHANGING_METHODS and is_cross_origin(
            _header_values(scope, b"sec-fetch-site"),
            _header_values(scope, b"origin"),
            authority,
            gateway_origin,
        ):
            logger.warning("Request refused: cross-origin state-changing request")
            await JSONResponse({"detail": CROSS_ORIGIN_REFUSED}, status_code=403)(
                scope, receive, send
            )
            return
        await self.app(scope, receive, send)
