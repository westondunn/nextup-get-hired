"""Correspondence sync settings and manual trigger. Read-only Gmail; nothing is sent."""

import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import google_credentials
from app.application_intake import ensure_review_rule
from app.config import get_settings
from app.correspondence_tasks import review_count, sync_calendar_task, sync_gmail_task
from app.db import get_session
from app.followup_tasks import INBOUND_REPLY_RULE
from app.local_session import require_session
from app.models import CorrespondenceSyncSettings, FollowUpRule

router = APIRouter(prefix="/api/correspondence", tags=["correspondence"])
Database = Annotated[Session, Depends(get_session)]
logger = logging.getLogger(__name__)

GMAIL_SWITCHED_OFF = (
    "Gmail sync is switched off in this installation's configuration and cannot be turned on "
    "from here."
)
CALENDAR_SWITCHED_OFF = (
    "Calendar sync is switched off in this installation's configuration and cannot be turned "
    "on from here."
)
GMAIL_NOT_CONNECTED = (
    "Gmail sync cannot be turned on yet: no Google connection that includes Gmail access "
    "can be used."
)
CALENDAR_NOT_CONNECTED = (
    "Calendar sync cannot be turned on yet: no Google connection that includes Calendar "
    "access can be used."
)


class CorrespondenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool = False
    query: str = Field(
        default="label:job-search",
        min_length=1,
        max_length=500,
        pattern=r"^[^\x00\n\r]+$",
    )
    max_messages_per_run: int = Field(default=25, ge=1, le=200)
    calendar_enabled: bool = False
    calendar_lookahead_days: int = Field(default=14, ge=1, le=60)
    # Opt-in: a recognized application confirmation creates or advances an application.
    auto_create_applications: bool = False


def _out(config: CorrespondenceSyncSettings | None, session: Session) -> dict:
    settings = get_settings()
    body = (
        {key: getattr(config, key) for key in CorrespondenceInput.model_fields}
        if config
        else CorrespondenceInput().model_dump()
    )
    return {
        **body,
        "live_enabled": settings.gmail_sync_enabled,
        # Whether a sync would have credentials to use: a stored connection that grants
        # the capability, or the complete fallback in configuration.
        "credentials_present": google_credentials.usable(session, settings, "gmail"),
        "calendar_credentials_present": google_credentials.usable(session, settings, "calendar"),
        "interval_seconds": settings.gmail_sync_interval_seconds,
        "last_run_at": config.last_run_at if config else None,
        "last_status": config.last_status if config else "not_run",
        "last_error": config.last_error if config else "",
        "last_imported": config.last_imported if config else 0,
        "cursor_epoch": config.cursor_epoch if config else None,
        "calendar_live_enabled": settings.calendar_sync_enabled,
        "calendar_interval_seconds": settings.calendar_sync_interval_seconds,
        "calendar_last_run_at": config.calendar_last_run_at if config else None,
        "calendar_last_status": config.calendar_last_status if config else "not_run",
        "calendar_last_error": config.calendar_last_error if config else "",
        "calendar_last_imported": config.calendar_last_imported if config else 0,
        "review_count": review_count(session),
    }


@router.get("")
def read_correspondence(session: Database):
    return _out(session.get(CorrespondenceSyncSettings, 1), session)


# Changing or triggering sync needs a local session (docs/decisions/0001-local-session-boundary.md).
@router.put("", dependencies=[Depends(require_session)])
def save_correspondence(body: CorrespondenceInput, session: Database):
    settings = get_settings()
    # Turning a sync on needs its flag in configuration and credentials it could use
    # (decision 0003, section 9).
    if body.enabled:
        if not settings.gmail_sync_enabled:
            raise HTTPException(409, GMAIL_SWITCHED_OFF)
        if not google_credentials.usable(session, settings, "gmail"):
            raise HTTPException(409, GMAIL_NOT_CONNECTED)
    if body.calendar_enabled:
        if not settings.calendar_sync_enabled:
            raise HTTPException(409, CALENDAR_SWITCHED_OFF)
        if not google_credentials.usable(session, settings, "calendar"):
            raise HTTPException(409, CALENDAR_NOT_CONNECTED)
    session.execute(insert(CorrespondenceSyncSettings).values(id=1).on_conflict_do_nothing())
    config = session.get(CorrespondenceSyncSettings, 1, with_for_update=True)
    if config.query != body.query:
        config.cursor_epoch = None  # A new query must re-scan the initial window.
    for key, value in body.model_dump().items():
        setattr(config, key, value)
    config.updated_at = datetime.now(UTC)
    if body.enabled:
        _ensure_reply_rule(session)
    if body.auto_create_applications:
        ensure_review_rule(session)
    session.commit()
    return _out(config, session)


def _ensure_reply_rule(session: Session) -> None:
    """Seed the missed-reply rule once; the user owns it afterwards via /api/follow-up-rules."""
    if session.scalar(select(FollowUpRule).where(FollowUpRule.rule_key == INBOUND_REPLY_RULE)):
        return
    now = datetime.now(UTC)
    session.add(
        FollowUpRule(
            id=uuid4(),
            rule_key=INBOUND_REPLY_RULE,
            trigger="inbound_message_without_reply",
            delay_business_days=3,
            action="create_review_task",
            contact_required_for_outreach=False,
            enabled=True,
            config={"seeded_by": "correspondence_sync"},
            created_at=now,
            updated_at=now,
        )
    )


@router.post("/sync", status_code=202, dependencies=[Depends(require_session)])
def run_sync(session: Database):
    config = session.get(CorrespondenceSyncSettings, 1)
    tasks = []
    if config is not None and config.enabled:
        tasks.append(("gmail", sync_gmail_task))
    if config is not None and config.calendar_enabled:
        tasks.append(("calendar", sync_calendar_task))
    if not tasks:
        raise HTTPException(409, "Turn on Gmail or Calendar sync before requesting a check.")
    try:
        for _, task in tasks:
            task.apply_async(retry=False, expires=120)
    except Exception as exc:
        logger.warning("Correspondence sync publish failed (%s)", type(exc).__name__)
        raise HTTPException(503, "Sync could not be queued; the broker is unavailable.") from exc
    return {"queued": True, "tasks": [name for name, _ in tasks]}
