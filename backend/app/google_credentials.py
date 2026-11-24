"""Which Google credentials a sync uses: the stored connection, or the configuration fallback.

See docs/decisions/0003-google-connection.md, sections 7 and 9.

A stored connection is always used when one exists, whatever state it is in. One that
needs reauthorization, lacks the capability or cannot be read stops that capability with a
fixed reason; the fallback is not used in its place. The credentials in configuration are
used only when no grant is stored and all three are present.

Nothing here logs, and no error carries a credential.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import google_lifecycle, token_vault
from app.config import Settings
from app.google_connection import CLIENT_SECRET_PURPOSE, KEY_VERSION, REFRESH_TOKEN_PURPOSE
from app.models import GoogleConnection, GoogleLifecycle
from app.sources import gmail, google_calendar
from app.sources.common import SourceError, require_live_requests
from app.sources.google_oauth import CAPABILITY_SCOPES, TOKEN

NAMES = {"gmail": "Gmail", "calendar": "Calendar"}
CHECKED = {
    "gmail": gmail.checked_access_token,
    "calendar": google_calendar.checked_access_token,
}

NOT_CONNECTED = "No Google account is connected. Connect one in Settings."
NEEDS_REAUTHORIZATION = "The Google connection has to be authorized again in Settings."
UNREADABLE = (
    "The stored Google connection cannot be read with the current encryption key. "
    "Connect the account again."
)
NOT_UPDATED = "Google issued a new refresh token, and it could not be stored. Sync stopped."


def not_granted(capability: str) -> str:
    return (
        f"The Google connection does not include {NAMES[capability]} access. "
        "Connect the account again and grant it."
    )


@dataclass(frozen=True, repr=False)
class Credentials:
    """What a token refresh needs. It has no ``repr``, so it cannot be printed by mistake."""

    client_id: str
    client_secret: str
    refresh_token: str
    # The sealed form the refresh token was read from; ``None`` for the fallback.
    stored_as: str | None = None
    epoch: UUID | None = None
    generation: UUID | None = None


def resolve(
    session: Session,
    settings: Settings,
    capability: str,
    *,
    lifecycle: GoogleLifecycle | None = None,
) -> Credentials:
    """The credentials for one capability, or a ``SourceError`` saying why there are none.

    Contacts nothing. In fixture data mode it refuses before any credential is opened.
    """
    require_live_requests(settings)
    if lifecycle is None:
        lifecycle = google_lifecycle.lifecycle_row(session)
    row = session.get(GoogleConnection, 1, populate_existing=True)
    if row is None or row.refresh_token_sealed is None:
        if not gmail.credentials_present(settings):
            raise SourceError("not_connected", NOT_CONNECTED)
        return Credentials(
            client_id=settings.google_oauth_client_id.get_secret_value(),
            client_secret=settings.google_oauth_client_secret.get_secret_value(),
            refresh_token=settings.gmail_refresh_token.get_secret_value(),
            epoch=lifecycle.epoch,
        )
    if row.state != "connected":
        raise SourceError("needs_reauthorization", NEEDS_REAUTHORIZATION)
    if CAPABILITY_SCOPES[capability] not in (row.granted_scopes or []):
        raise SourceError("capability_not_granted", not_granted(capability))
    try:
        return Credentials(
            client_id=row.client_id,
            client_secret=token_vault.open_sealed(
                row.client_secret_sealed, purpose=CLIENT_SECRET_PURPOSE, settings=settings
            ),
            refresh_token=token_vault.open_sealed(
                row.refresh_token_sealed, purpose=REFRESH_TOKEN_PURPOSE, settings=settings
            ),
            stored_as=row.refresh_token_sealed,
            epoch=lifecycle.epoch,
            generation=lifecycle.generation,
        )
    except token_vault.VaultError:
        raise SourceError("connection_unreadable", UNREADABLE) from None


def usable(session: Session, settings: Settings, capability: str) -> bool:
    """Whether a sync of this capability would have credentials to use."""
    try:
        resolve(session, settings, capability)
    except SourceError:
        return False
    return True


def _connection_session(session: Session) -> Session:
    """A session of its own on the same database, for one short change to the connection."""
    return Session(session.get_bind())


def _update_current_grant(
    session: Session, settings: Settings, credentials: Credentials, *, replacement: str | None
) -> bool:
    """Rotate a token, or mark a definite invalid grant, only if the original is current."""
    if credentials.stored_as is None:
        return False
    try:
        with _connection_session(session) as short, short.begin():
            lifecycle = google_lifecycle.lifecycle_row(short, lock=True)
            if (
                lifecycle.generation != credentials.generation
                or lifecycle.epoch != credentials.epoch
            ):
                return False
            row = short.get(GoogleConnection, 1, with_for_update=True, populate_existing=True)
            if (
                row is None
                or row.state != "connected"
                or row.refresh_token_sealed != credentials.stored_as
            ):
                return False
            if replacement is None:
                row.state = "needs_reauthorization"
            else:
                row.refresh_token_sealed = token_vault.seal(
                    replacement, purpose=REFRESH_TOKEN_PURPOSE, settings=settings
                )
                row.key_version = KEY_VERSION
            row.updated_at = datetime.now(UTC)
            return True
    except (SQLAlchemyError, token_vault.VaultError):
        raise SourceError("connection_not_updated", NOT_UPDATED) from None


def keep_new_refresh_token(
    session: Session, settings: Settings, credentials: Credentials, payload: dict
) -> None:
    issued = payload.get("refresh_token")
    if isinstance(issued, str) and issued != credentials.refresh_token and TOKEN.fullmatch(issued):
        _update_current_grant(session, settings, credentials, replacement=issued)


def refresh_refusal(
    session: Session, settings: Settings, credentials: Credentials, error: SourceError
) -> SourceError:
    if error.code != "invalid_grant":
        return error
    if credentials.stored_as is None or _update_current_grant(
        session, settings, credentials, replacement=None
    ):
        return SourceError("needs_reauthorization", NEEDS_REAUTHORIZATION)
    return SourceError("provider_rejected", "Google rejected an earlier refresh grant.")


def access_token(
    client: httpx.Client,
    session: Session,
    settings: Settings,
    credentials: Credentials,
    capability: str,
) -> str:
    """An access token for one capability. One request; a refusal is not retried."""
    try:
        payload = gmail.request_access_token(
            client,
            settings,
            client_id=credentials.client_id,
            client_secret=credentials.client_secret,
            refresh_token=credentials.refresh_token,
        )
    except SourceError as error:
        raise refresh_refusal(session, settings, credentials, error) from None
    keep_new_refresh_token(session, settings, credentials, payload)
    return CHECKED[capability](payload)
