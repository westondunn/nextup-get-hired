"""The stored Google connection: saving and reporting the user's own OAuth client.

See docs/decisions/0003-google-connection.md. The user registers an OAuth client with
Google and enters its ID and secret here, under a local session. The secret is sealed by
``app.token_vault`` before it is stored and is never returned.

Nothing in this module contacts Google. The consent flow is in ``app.google_consent``.
Nothing here logs or returns a client secret, and no error repeats what was submitted.
"""

import json
import re
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import token_vault
from app.config import Settings, get_settings
from app.db import get_session
from app.local_session import require_session
from app.models import GoogleConnection
from app.sources.common import SourceError, require_live_requests
from app.sources.google_oauth import capabilities_of

router = APIRouter(prefix="/api/google", tags=["google"])
Database = Annotated[Session, Depends(get_session)]

# What a sealed value is bound to. A value sealed for one cannot be opened as the other.
CLIENT_SECRET_PURPOSE = "google.client_secret"
REFRESH_TOKEN_PURPOSE = "google.refresh_token"
# There is one key and no rotation yet (decision 0003, section 6).
KEY_VERSION = 1

MAX_BODY_BYTES = 4096
# The form Google issues for an OAuth client. Requiring it also keeps a secret pasted into
# the wrong field from being stored as plain text.
CLIENT_ID = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]{0,180}\.apps\.googleusercontent\.com")
CLIENT_SECRET = re.compile(r"[\x21-\x7e]{1,512}")

FIXTURE_MODE = "Google connections are not available in fixture data mode."
SWITCHED_OFF = (
    "Gmail and Calendar sync are switched off in this installation's configuration, so no "
    "Google client can be saved."
)
NO_KEY = "No encryption key is configured, so a Google client cannot be stored."
INVALID_REQUEST = "Invalid Google client request."
INVALID_CLIENT_ID = "The client ID must be the full value ending in .apps.googleusercontent.com."
INVALID_CLIENT_SECRET = "The client secret is empty, too long, or contains a space."
CLIENT_IN_USE = (
    "A Google account is connected with the current client. Disconnect it before saving a "
    "different client ID."
)


def unavailable_reason(settings: Settings) -> str | None:
    """Why no connection can be stored in this installation, or ``None`` when one can.

    Fixture data mode is checked first, as for every provider path. Staging can have
    neither a sync flag nor a key (``NXG-C09``), so it is always refused here.
    """
    try:
        require_live_requests(settings)
    except SourceError:
        return "fixture_mode"
    if not (settings.gmail_sync_enabled or settings.calendar_sync_enabled):
        return "switched_off"
    if not token_vault.available(settings):
        return "no_key"
    return None


def require_available(settings: Settings) -> None:
    """Refuse with a fixed message when no connection can be stored here."""
    reason = unavailable_reason(settings)
    if reason == "fixture_mode":
        raise HTTPException(409, FIXTURE_MODE)
    if reason == "switched_off":
        raise HTTPException(409, SWITCHED_OFF)
    if reason == "no_key":
        raise HTTPException(503, NO_KEY)


def _state(row: GoogleConnection | None, settings: Settings) -> str:
    """The stored state, or why there is none to report."""
    if row is None:
        return "not_configured"
    try:
        token_vault.open_sealed(
            row.client_secret_sealed, purpose=CLIENT_SECRET_PURPOSE, settings=settings
        )
        if row.refresh_token_sealed is not None:
            token_vault.open_sealed(
                row.refresh_token_sealed, purpose=REFRESH_TOKEN_PURPOSE, settings=settings
            )
    except token_vault.VaultError:
        return "unreadable"
    return row.state


def _out(row: GoogleConnection | None, settings: Settings) -> dict:
    reason = unavailable_reason(settings)
    return {
        "available": reason is None,
        "unavailable_reason": reason,
        "client_configured": row is not None,
        "client_id": row.client_id if row is not None else None,
        "state": _state(row, settings),
        # What this installation's configuration allows to be connected and used.
        "enabled_capabilities": [
            name
            for name, enabled in (
                ("gmail", settings.gmail_sync_enabled),
                ("calendar", settings.calendar_sync_enabled),
            )
            if enabled
        ],
        # What Google granted, whatever was asked for and whatever NextUp is set to use.
        "granted_capabilities": list(capabilities_of(row.granted_scopes or [])) if row else [],
        "account_address": row.account_address if row is not None else None,
    }


async def _submitted_client(request: Request) -> tuple[str, str]:
    """The ``client_id`` and ``client_secret`` of the request body.

    Parsed by hand: the framework's own validation errors repeat the submitted body, and
    the body holds a secret.
    """
    body = await request.body()
    try:
        if len(body) > MAX_BODY_BYTES:
            raise ValueError
        payload = json.loads(body)
        if not isinstance(payload, dict) or set(payload) != {"client_id", "client_secret"}:
            raise ValueError
        client_id, client_secret = payload["client_id"], payload["client_secret"]
        if not isinstance(client_id, str) or not isinstance(client_secret, str):
            raise ValueError
    except (ValueError, RecursionError):
        raise HTTPException(422, INVALID_REQUEST) from None
    if not CLIENT_ID.fullmatch(client_id):
        raise HTTPException(422, INVALID_CLIENT_ID)
    if not CLIENT_SECRET.fullmatch(client_secret):
        raise HTTPException(422, INVALID_CLIENT_SECRET)
    return client_id, client_secret


SubmittedClient = Annotated[tuple[str, str], Depends(_submitted_client)]


# Every connection route needs a local session (docs/decisions/0001-local-session-boundary.md).
@router.get("/connection", dependencies=[Depends(require_session)])
def read_connection(session: Database):
    return _out(session.get(GoogleConnection, 1), get_settings())


@router.put("/client", dependencies=[Depends(require_session)])
def save_client(client: SubmittedClient, session: Database):
    settings = get_settings()
    require_available(settings)
    client_id, client_secret = client
    sealed = token_vault.seal(client_secret, purpose=CLIENT_SECRET_PURPOSE, settings=settings)
    session.execute(
        insert(GoogleConnection)
        .values(id=1, client_id=client_id, client_secret_sealed=sealed, key_version=KEY_VERSION)
        .on_conflict_do_nothing()
    )
    # Every change to the connection takes this row lock (decision 0003, section 7).
    row = session.get(GoogleConnection, 1, with_for_update=True)
    if row.state != "not_connected" and row.client_id != client_id:
        # A refresh token belongs to the client it was issued to.
        session.rollback()
        raise HTTPException(409, CLIENT_IN_USE)
    row.client_id = client_id
    row.client_secret_sealed = sealed
    row.key_version = KEY_VERSION
    row.updated_at = datetime.now(UTC)
    session.commit()
    return _out(row, settings)
