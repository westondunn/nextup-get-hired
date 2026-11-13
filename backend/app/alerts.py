from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.alert_tasks import check_alerts
from app.db import get_session
from app.jobs import JobOut
from app.models import JobAlert, Profile, SavedSearch
from app.saved_searches import SearchOut

router = APIRouter(prefix="/api", tags=["local alerts"])
Database = Annotated[Session, Depends(get_session)]


class AlertSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool
    min_score: int = Field(ge=0, le=100, default=70)


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    search_id: UUID
    search_name: str
    job: JobOut
    created_at: datetime
    read_at: datetime | None


class InboxPage(BaseModel):
    items: list[AlertOut]
    total: int
    unread: int


def locked_search(session, search_id):
    row = session.scalar(select(SavedSearch).where(SavedSearch.id == search_id).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="Saved search not found.")
    return row


@router.put("/saved-searches/{search_id}/alerts", response_model=SearchOut)
def configure_alerts(search_id: UUID, body: AlertSettings, session: Database):
    row = locked_search(session, search_id)
    if body.enabled and session.get(Profile, 1) is None:
        raise HTTPException(status_code=409, detail="Save a profile before enabling match alerts.")
    row.alerts_enabled = body.enabled
    row.alert_min_score = body.min_score
    row.alert_check_status = "pending" if body.enabled else "disabled"
    row.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(row)
    return row


@router.post("/saved-searches/{search_id}/alerts/check", response_model=SearchOut, status_code=202)
def request_check(search_id: UUID, session: Database):
    row = locked_search(session, search_id)
    if not row.alerts_enabled:
        raise HTTPException(
            status_code=409, detail="Enable local alerts for this saved search first."
        )
    if row.alert_check_status == "queued":
        raise HTTPException(
            status_code=409,
            detail="An alert check is already queued; the scheduled check can also complete it.",
        )
    row.alert_check_status = "queued"
    session.commit()
    session.refresh(row)
    response = SearchOut.model_validate(row)
    try:
        check_alerts.apply_async(kwargs={"search_id": str(search_id)}, retry=False)
    except Exception:
        session.execute(
            update(SavedSearch)
            .where(
                SavedSearch.id == search_id,
                SavedSearch.alert_check_status == "queued",
            )
            .values(alert_check_status="publish_failed")
        )
        session.commit()
        raise HTTPException(
            status_code=503,
            detail=(
                "Alert check delivery is unconfirmed. "
                "The scheduled check will retry enabled searches."
            ),
        ) from None
    return response


@router.get("/alerts", response_model=InboxPage)
def read_alerts(
    session: Database,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    predicate = JobAlert.read_at.is_(None) if unread_only else True
    return {
        "items": session.scalars(
            select(JobAlert)
            .where(predicate)
            .order_by(JobAlert.created_at.desc(), JobAlert.id)
            .offset(offset)
            .limit(limit)
        ).all(),
        "total": session.scalar(select(func.count()).select_from(JobAlert).where(predicate)),
        "unread": session.scalar(
            select(func.count()).select_from(JobAlert).where(JobAlert.read_at.is_(None))
        ),
    }


@router.put("/alerts/{alert_id}/read", response_model=AlertOut)
def mark_read(alert_id: UUID, session: Database):
    row = session.scalar(select(JobAlert).where(JobAlert.id == alert_id).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="Alert not found.")
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
    session.commit()
    session.refresh(row)
    return row
