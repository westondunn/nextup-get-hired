"""Database state and process-independent serialization for Google lifecycle actions."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from app.models import GoogleLifecycle

# Application-reserved PostgreSQL advisory lock key for the single Google lifecycle.
ACTION_LOCK_KEY = 0x4E585550474F4F47
BUSY_MESSAGE = "Another Google connection action is in progress. Try again."


class LifecycleBusy(Exception):
    """Another connection action holds the lifecycle advisory lock."""


def lifecycle_row(session: Session, *, lock: bool = False) -> GoogleLifecycle:
    """Read fresh lifecycle state. Lock it before taking a Google connection row lock."""
    row = session.get(GoogleLifecycle, 1, with_for_update=lock, populate_existing=True)
    if row is None:
        raise NoResultFound("Google lifecycle state is unavailable.")
    return row


@contextmanager
def action(session: Session) -> Iterator[None]:
    """Serialize interactive actions without holding a row lock during provider requests."""
    bind = session.get_bind()
    engine = bind.engine if isinstance(bind, Connection) else bind
    with engine.connect() as guard:
        try:
            acquired = guard.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": ACTION_LOCK_KEY}
            )
            guard.commit()
        except BaseException:
            # Never return a connection with an uncertain session-level lock to the pool.
            guard.invalidate()
            raise
        if not acquired:
            raise LifecycleBusy(BUSY_MESSAGE)
        try:
            yield
        finally:
            try:
                released = guard.scalar(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": ACTION_LOCK_KEY}
                )
                guard.commit()
                if not released:
                    guard.invalidate()
            except BaseException:
                guard.invalidate()
                raise


def advance_generation(row: GoogleLifecycle) -> None:
    row.generation = uuid4()
    row.imports_since = datetime.now(UTC)
    row.gmail_last_success_at = None
    row.calendar_last_success_at = None
    row.gmail_attempt_generation = None
    row.calendar_attempt_generation = None


def invalidate(row: GoogleLifecycle) -> None:
    """Fence old callbacks, workers and sync evidence, and stop both syncs."""
    row.epoch = uuid4()
    advance_generation(row)
    row.generation = None
    row.sync_paused = True
