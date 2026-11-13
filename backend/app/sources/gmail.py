"""Read-only Gmail adapter: OAuth refresh, bounded listing, and message parsing.

Only the ``gmail.readonly`` scope is ever requested. Nothing here sends, labels,
or modifies mail. Network access is explicit and bounded so tests can inject a
mocked ``httpx.Client``.
"""

import base64
import binascii
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parseaddr

import httpx

from app.config import Settings
from app.sources.common import SourceError, plain_text, require_live_requests

logging.getLogger("httpx").setLevel(logging.WARNING)

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
MAX_LIST_PAGES = 5
LIST_PAGE_SIZE = 100
MAX_BODY_CHARS = 100_000  # whole messages; the UI shows them in full
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class ParsedMessage:
    source_id: str
    thread_id: str
    sender_name: str
    sender_email: str
    subject: str
    body: str
    received_at: datetime
    recipient_email: str = ""
    is_sent: bool = False  # carries Gmail's SENT label: the user wrote it
    auto_reply: bool = False  # RFC 3834 Auto-Submitted: auto-replied


def credentials_present(settings: Settings) -> bool:
    return bool(
        settings.google_oauth_client_id.get_secret_value()
        and settings.google_oauth_client_secret.get_secret_value()
        and settings.gmail_refresh_token.get_secret_value()
    )


def _read_json(client: httpx.Client, method: str, url: str, **kwargs) -> dict:
    try:
        response = client.request(method, url, **kwargs)
    except httpx.RequestError:
        raise SourceError("network_error", "Gmail could not be reached.") from None
    if response.status_code in (401, 403):
        raise SourceError(
            "unauthorized", "Gmail rejected the stored credentials; re-authorize Google access."
        )
    if response.status_code == 429 or response.status_code >= 500:
        raise SourceError("provider_unavailable", "Gmail is temporarily unavailable.")
    if response.status_code != 200:
        raise SourceError("provider_rejected", f"Gmail returned HTTP {response.status_code}.")
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise SourceError("too_large", "Gmail response exceeded the 4 MB limit.")
    try:
        payload = response.json()
    except ValueError:
        raise SourceError("invalid_response", "Gmail returned invalid JSON.") from None
    if not isinstance(payload, dict):
        raise SourceError("invalid_response", "Gmail returned an unexpected payload.")
    return payload


def refresh_access_token(client: httpx.Client, settings: Settings) -> str:
    require_live_requests(settings)
    if not credentials_present(settings):
        raise SourceError("not_configured", "Gmail credentials are not configured.")
    payload = _read_json(
        client,
        "POST",
        TOKEN_URL,
        data={
            "client_id": settings.google_oauth_client_id.get_secret_value(),
            "client_secret": settings.google_oauth_client_secret.get_secret_value(),
            "refresh_token": settings.gmail_refresh_token.get_secret_value(),
            "grant_type": "refresh_token",
        },
    )
    token = payload.get("access_token")
    scope = payload.get("scope", SCOPE)
    if not isinstance(token, str) or not token:
        raise SourceError("unauthorized", "Gmail did not return an access token.")
    if scope and SCOPE not in scope.split():
        raise SourceError("wrong_scope", "The stored token lacks the Gmail read-only scope.")
    return token


def list_message_refs(
    client: httpx.Client, token: str, query: str, max_ids: int
) -> list[tuple[str, str]]:
    """Return up to ``max_ids`` (message id, thread id) pairs matching ``query``."""
    refs: list[tuple[str, str]] = []
    page_token = None
    for _ in range(MAX_LIST_PAGES):
        params = {"q": query, "maxResults": min(LIST_PAGE_SIZE, max_ids - len(refs))}
        if page_token:
            params["pageToken"] = page_token
        payload = _read_json(
            client,
            "GET",
            f"{API_BASE}/messages",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        for item in payload.get("messages") or []:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                refs.append((item["id"], str(item.get("threadId") or "")))
            if len(refs) >= max_ids:
                return refs
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return refs


def fetch_message(client: httpx.Client, token: str, message_id: str) -> dict:
    return _read_json(
        client,
        "GET",
        f"{API_BASE}/messages/{message_id}",
        params={"format": "full"},
        headers={"Authorization": f"Bearer {token}"},
    )


def profile_email(client: httpx.Client, token: str) -> str:
    """The mailbox owner's address, used to recognize the user's own messages."""
    payload = _read_json(
        client, "GET", f"{API_BASE}/profile", headers={"Authorization": f"Bearer {token}"}
    )
    return str(payload.get("emailAddress") or "").strip().lower()


def _decode(data: str) -> str:
    try:
        raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    except (binascii.Error, ValueError):
        return ""
    return raw.decode("utf-8", errors="replace")


def _collect_bodies(part: dict, found: dict[str, str]) -> None:
    if not isinstance(part, dict):
        return
    mime = str(part.get("mimeType") or "")
    data = (part.get("body") or {}).get("data")
    if isinstance(data, str) and mime in ("text/plain", "text/html") and mime not in found:
        found[mime] = _decode(data)
    for child in part.get("parts") or []:
        _collect_bodies(child, found)


def parse_message(payload: dict) -> ParsedMessage:
    message_id = payload.get("id")
    if not isinstance(message_id, str) or not message_id:
        raise SourceError("invalid_response", "Gmail message lacked an id.")
    headers = {
        str(h.get("name", "")).lower(): str(h.get("value", ""))
        for h in (payload.get("payload") or {}).get("headers") or []
        if isinstance(h, dict)
    }
    name, address = parseaddr(headers.get("from", ""))
    bodies: dict[str, str] = {}
    _collect_bodies(payload.get("payload") or {}, bodies)
    body = bodies.get("text/plain") or plain_text(bodies.get("text/html", ""))
    if not body:
        body = str(payload.get("snippet") or "")
    body = body.replace("\x00", "")[:MAX_BODY_CHARS]
    try:
        received_at = datetime.fromtimestamp(int(payload.get("internalDate", 0)) / 1000, tz=UTC)
    except (TypeError, ValueError, OverflowError):
        received_at = datetime.now(UTC)
    return ParsedMessage(
        source_id=message_id,
        thread_id=str(payload.get("threadId") or ""),
        sender_name=name.strip()[:200],
        sender_email=address.strip().lower()[:320],
        subject=headers.get("subject", "").replace("\x00", "")[:500],
        body=body,
        received_at=received_at,
        recipient_email=parseaddr(headers.get("to", ""))[1].strip().lower()[:320],
        is_sent="SENT" in (payload.get("labelIds") or []),
        auto_reply=headers.get("auto-submitted", "").strip().lower().startswith("auto-replied"),
    )
