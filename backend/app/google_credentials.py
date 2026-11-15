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

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import token_vault
from app.config import Settings
from app.google_connection import CLIENT_SECRET_PURPOSE, KEY_VERSION, REFRESH_TOKEN_PURPOSE
from app.models import GoogleConnection
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


def resolve(session: Session, settings: Settings, capability: str) -> Credentials:
    """The credentials for one capability, or a ``SourceError`` saying why there are none.

    Contacts nothing. In fixture data mode it refuses before any credential is opened.
    """
    require_live_requests(settings)
    row = session.get(GoogleConnection, 1)
    if row is None or row.refresh_token_sealed is None:
        if not gmail.credentials_present(settings):
            raise SourceError("not_connected", NOT_CONNECTED)
        return Credentials(
            client_id=settings.google_oauth_client_id.get_secret_value(),
            client_secret=settings.google_oauth_client_secret.get_secret_value(),
            refresh_token=settings.gmail_refresh_token.get_secret_value(),
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


def _keep_new_refresh_token(
    session: Session, settings: Settings, credentials: Credentials, payload: dict
) -> None:
    """Store a refresh token that Google issued in place of the one just used.

    The change is made under the connection's row lock, in a transaction of its own, so
    the lock is not held for the rest of the sync. It is made only if the stored token is
    still the one that was used: a connection replaced in the meantime is left alone.
    """
    issued = payload.get("refresh_token")
    if credentials.stored_as is None or not isinstance(issued, str):
        return
    if issued == credentials.refresh_token or not TOKEN.fullmatch(issued):
        return
    try:
        with _connection_session(session) as short, short.begin():
            row = short.get(GoogleConnection, 1, with_for_update=True, populate_existing=True)
            if row is None or row.refresh_token_sealed != credentials.stored_as:
                return
            row.refresh_token_sealed = token_vault.seal(
                issued, purpose=REFRESH_TOKEN_PURPOSE, settings=settings
            )
            row.key_version = KEY_VERSION
            row.updated_at = datetime.now(UTC)
    except SQLAlchemyError:
        # The sync stops with a fixed reason instead of going on with a token that the
        # stored connection may no longer be able to renew.
        raise SourceError("connection_not_updated", NOT_UPDATED) from None


def access_token(
    client: httpx.Client,
    session: Session,
    settings: Settings,
    credentials: Credentials,
    capability: str,
) -> str:
    """An access token for one capability. One request; a refusal is not retried."""
    payload = gmail.request_access_token(
        client,
        settings,
        client_id=credentials.client_id,
        client_secret=credentials.client_secret,
        refresh_token=credentials.refresh_token,
    )
    _keep_new_refresh_token(session, settings, credentials, payload)
    return CHECKED[capability](payload)
