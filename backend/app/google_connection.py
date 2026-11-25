"""The stored Google connection: saving and reporting the user's own OAuth client.

See docs/decisions/0003-google-connection.md. The user registers an OAuth client with
Google and enters its ID and secret here, under a local session. The secret is sealed by
``app.token_vault`` before it is stored and is never returned.

Nothing in this module contacts Google. The consent flow is in ``app.google_consent``.
Nothing here logs or returns a client secret, and no error repeats what was submitted.
"""

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import google_lifecycle, token_vault
from app.config import Settings, get_settings
from app.db import get_session
from app.local_session import require_session
from app.models import CorrespondenceSyncSettings, GoogleConnection, GoogleLifecycle
from app.sources import gmail
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


# Keep provider and adapter details out of the lifecycle report. The correspondence API
# continues to return its own result codes.
ATTEMPT_STATUS = {
    "ok": "ok",
    "disabled": "disabled",
    "fixture_mode": "disabled",
    "not_configured": "not_configured",
    "not_connected": "not_configured",
    "needs_reauthorization": "needs_reauthorization",
    "invalid_grant": "needs_reauthorization",
    "capability_not_granted": "wrong_scope",
    "wrong_scope": "wrong_scope",
    "admin_restricted": "admin_restricted",
    "admin_policy_rejected": "admin_restricted",
    "network_error": "temporarily_unavailable",
    "provider_unavailable": "temporarily_unavailable",
    "temporarily_unavailable": "temporarily_unavailable",
    "connection_unreadable": "unreadable",
    "connection_not_updated": "connection_error",
    "not_run": "not_run",
}


def _sync_status(
    name: str,
    config: CorrespondenceSyncSettings | None,
    lifecycle: GoogleLifecycle,
    *,
    eligible: bool,
    stored: bool,
    interval: int,
    now: datetime,
) -> dict:
    prefix = "" if name == "gmail" else "calendar_"
    active = bool(
        eligible and not lifecycle.sync_paused and config and getattr(config, prefix + "enabled")
    )
    success = None
    attempt = None
    status = "not_run"
    if stored and lifecycle.generation is not None:
        success = getattr(lifecycle, name + "_last_success_at")
        if config and getattr(lifecycle, name + "_attempt_generation") == lifecycle.generation:
            attempt = getattr(config, prefix + "last_run_at")
            if attempt is not None:
                status = ATTEMPT_STATUS.get(
                    getattr(config, prefix + "last_status"), "provider_rejected"
                )
    freshness = "inactive"
    if active:
        if success is None:
            freshness = "unknown"
        elif now - success > timedelta(seconds=2 * interval):
            freshness = "stale"
        else:
            freshness = "current"
    return {
        "active": active,
        "last_attempt_at": attempt,
        "last_status": status,
        "last_success_at": success,
        "freshness": freshness,
    }


def connection_status(session: Session, settings: Settings) -> dict:
    # One snapshot keeps the account, its grant and its sync evidence together even if a
    # disconnect or reauthorization commits while the status request is running.
    lifecycle, row, config = session.execute(
        select(GoogleLifecycle, GoogleConnection, CorrespondenceSyncSettings)
        .select_from(GoogleLifecycle)
        .outerjoin(GoogleConnection, GoogleConnection.id == GoogleLifecycle.id)
        .outerjoin(CorrespondenceSyncSettings, CorrespondenceSyncSettings.id == GoogleLifecycle.id)
        .where(GoogleLifecycle.id == 1)
        .execution_options(populate_existing=True)
    ).one()
    reason = unavailable_reason(settings)
    stored = row is not None and row.refresh_token_sealed is not None
    source = "none"
    if stored:
        source = "stored"
    elif gmail.credentials_present(settings):
        source = "configured"
    state = _state(row, settings)
    granted = list(capabilities_of(row.granted_scopes or [])) if row else []
    enabled = [name for name in ("gmail", "calendar") if getattr(settings, name + "_sync_enabled")]
    now = datetime.now(UTC)
    return {
        "available": reason is None,
        "unavailable_reason": reason,
        "client_configured": row is not None,
        "client_id": row.client_id if row is not None else None,
        "state": state,
        "enabled_capabilities": enabled,
        "granted_capabilities": granted,
        "account_address": row.account_address if row is not None else None,
        "credential_source": source,
        "sync": {
            name: _sync_status(
                name,
                config,
                lifecycle,
                eligible=(
                    not settings.fixture_data_mode
                    and name in enabled
                    and (
                        source == "configured"
                        or (stored and state == "connected" and name in granted)
                    )
                ),
                stored=stored,
                interval=getattr(settings, name + "_sync_interval_seconds"),
                now=now,
            )
            for name in ("gmail", "calendar")
        },
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
    try:
        return connection_status(session, get_settings())
    except SQLAlchemyError:
        raise HTTPException(
            503, {"code": "connection_error", "message": "The Google connection could not be read."}
        ) from None


@router.put("/client", dependencies=[Depends(require_session)])
def save_client(client: SubmittedClient, session: Database):
    settings = get_settings()
    require_available(settings)
    try:
        with google_lifecycle.action(session):
            return _save_client(session, settings, *client)
    except google_lifecycle.LifecycleBusy:
        raise HTTPException(
            409, {"code": "busy", "message": google_lifecycle.BUSY_MESSAGE}
        ) from None
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(
            503,
            {"code": "connection_error", "message": "The Google connection could not be saved."},
        ) from None


def _save_client(session: Session, settings: Settings, client_id: str, client_secret: str) -> dict:
    lifecycle = google_lifecycle.lifecycle_row(session, lock=True)
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
    # Every save installs a fresh sealed client secret, invalidating pending consent.
    lifecycle.epoch = uuid4()
    row.client_id = client_id
    row.client_secret_sealed = sealed
    row.key_version = KEY_VERSION
    row.updated_at = datetime.now(UTC)
    session.commit()
    return connection_status(session, settings)
