"""Google OAuth calls for a stored connection: consent address, code exchange, revocation.

See docs/decisions/0003-google-connection.md. Only the two read-only scopes below are ever
requested. Network access is explicit and bounded so tests can inject a mocked
``httpx.Client``, and every function that sends a request calls ``require_live_requests``
first.

No error raised here repeats anything Google returned, and nothing here logs.
"""

import base64
import hashlib
import re
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.config import Settings
from app.sources import gmail, google_calendar
from app.sources.common import SourceError, require_live_requests

# From Google's discovery document (https://accounts.google.com/.well-known/openid-configuration).
AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = gmail.TOKEN_URL
REVOCATION_URL = "https://oauth2.googleapis.com/revoke"
PRIMARY_CALENDAR_URL = "https://www.googleapis.com/calendar/v3/calendars/primary"

# One capability never implies the other (decision 0003, section 5).
CAPABILITY_SCOPES = {"gmail": gmail.SCOPE, "calendar": google_calendar.SCOPE}

MAX_RESPONSE_BYTES = 64 * 1024
MAX_SCOPES = 50
SCOPE = re.compile(r"[\x21-\x7e]{1,200}")
TOKEN = re.compile(r"[\x21-\x7e]{1,4096}")
ADDRESS = re.compile(r"[^\s@\x00-\x1f\x7f]{1,64}@[^\s@\x00-\x1f\x7f]{1,255}")
NO_ACCOUNT = "Google did not say which account was connected."


@dataclass(frozen=True, repr=False)
class Grant:
    """What a code exchange returned. It has no ``repr``, so it cannot be printed by mistake."""

    access_token: str
    refresh_token: str  # empty when Google returned none
    scopes: frozenset[str]

    def capabilities(self) -> tuple[str, ...]:
        """The capabilities this grant actually covers, whatever was asked for."""
        return capabilities_of(self.scopes)


def capabilities_of(scopes) -> tuple[str, ...]:
    return tuple(name for name, scope in CAPABILITY_SCOPES.items() if scope in scopes)


def code_challenge(verifier: str) -> str:
    """The ``S256`` challenge of a PKCE verifier (RFC 7636, section 4.2)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorization_url(
    *, client_id: str, redirect_uri: str, capabilities: tuple[str, ...], state: str, verifier: str
) -> str:
    """The address the browser is sent to for consent. Builds a string; sends nothing."""
    return (
        AUTHORIZATION_URL
        + "?"
        + urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(CAPABILITY_SCOPES[name] for name in capabilities),
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
                "state": state,
                "code_challenge": code_challenge(verifier),
                "code_challenge_method": "S256",
            }
        )
    )


def exchange_code(
    client: httpx.Client,
    settings: Settings,
    *,
    client_id: str,
    client_secret: str,
    code: str,
    verifier: str,
    redirect_uri: str,
) -> Grant:
    """Exchange an authorization code. The code is used once and never retried."""
    require_live_requests(settings)
    try:
        response = client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
        )
    except httpx.RequestError:
        raise SourceError("network_error", "Google could not be reached.") from None
    if response.status_code == 429 or response.status_code >= 500:
        raise SourceError("provider_unavailable", "Google is temporarily unavailable.")
    if response.status_code != 200:
        raise SourceError("exchange_refused", "Google refused the authorization code.")
    invalid = SourceError("invalid_response", "Google returned an unexpected token response.")
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise invalid
    try:
        payload = response.json()
    except ValueError:
        raise invalid from None
    if not isinstance(payload, dict):
        raise invalid
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token", "")
    scope = payload.get("scope")
    if not isinstance(access_token, str) or not TOKEN.fullmatch(access_token):
        raise invalid
    if not isinstance(refresh_token, str) or (refresh_token and not TOKEN.fullmatch(refresh_token)):
        raise invalid
    # Without the scope field there is no telling what was granted.
    if not isinstance(scope, str):
        raise invalid
    scopes = scope.split()
    if len(scopes) > MAX_SCOPES or not all(SCOPE.fullmatch(item) for item in scopes):
        raise invalid
    return Grant(access_token=access_token, refresh_token=refresh_token, scopes=frozenset(scopes))


def account_addresses(client: httpx.Client, settings: Settings, grant: Grant) -> tuple[str, ...]:
    """Every address the grant names for the account that consented. The first is stored.

    No identity scope is requested, so the address is read through the APIs the grant
    covers: Gmail's profile when mail was granted, and the identifier of the primary
    calendar when calendar was. Both are read when both were granted, because a later
    flow may cover only one of them and still has to recognize the same account.
    """
    require_live_requests(settings)
    lookups = []
    if gmail.SCOPE in grant.scopes:
        lookups.append((f"{gmail.API_BASE}/profile", "emailAddress"))
    if google_calendar.SCOPE in grant.scopes:
        lookups.append((PRIMARY_CALENDAR_URL, "id"))
    if not lookups:
        raise SourceError("no_account", NO_ACCOUNT)
    addresses = []
    for url, field in lookups:
        payload = gmail._read_json(
            client, "GET", url, headers={"Authorization": f"Bearer {grant.access_token}"}
        )
        value = payload.get(field)
        address = value.strip().lower() if isinstance(value, str) else ""
        if not ADDRESS.fullmatch(address) or len(address) > 320:
            raise SourceError("no_account", NO_ACCOUNT)
        if address not in addresses:
            addresses.append(address)
    return tuple(addresses)


def revoke(client: httpx.Client, settings: Settings, token: str) -> bool:
    """Ask Google to revoke a token, and with it the whole grant. ``True`` when it did.

    The token travels in the request body, never in the address.
    """
    require_live_requests(settings)
    try:
        response = client.post(REVOCATION_URL, data={"token": token})
    except httpx.RequestError:
        return False
    return response.status_code == 200
