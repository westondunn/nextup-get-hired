"""Campaign planning, task management, and Today view."""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Campaign, CampaignTask, Communication, Pursuit

router = APIRouter(tags=["campaign"])
Database = Annotated[Session, Depends(get_session)]

Category = Literal[
    "administration",
    "pipeline",
    "planning",
    "networking",
    "resume",
    "profile",
    "sourcing",
    "applications",
    "content",
    "interview",
    "follow_up",
    "review",
    "evidence",
    "other",
]
TaskStatus = Literal["planned", "in_progress", "waiting", "blocked", "completed", "canceled"]
Priority = Literal["P0", "P1", "P2", "P3"]
TERMINAL = {"completed", "canceled"}


# ---------- Schemas ----------


class CampaignInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign_key: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=300)
    start_date: date
    end_date: date
    timezone: str = Field(default="UTC", max_length=80)
    daily_capacity_minutes: int = Field(default=240, ge=30, le=720)
    preferences: dict = Field(default_factory=dict)


class CampaignUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=300)
    start_date: date | None = None
    end_date: date | None = None
    timezone: str | None = Field(default=None, max_length=80)
    daily_capacity_minutes: int | None = Field(default=None, ge=30, le=720)
    preferences: dict | None = None
    is_active: bool | None = None


class TaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seed_key: str | None = Field(default=None, max_length=20)
    title: str = Field(min_length=1, max_length=500)
    category: Category = "other"
    status: TaskStatus = "planned"
    priority: Priority = "P1"
    due_date: date | None = None
    estimated_minutes: int | None = Field(default=None, ge=1, le=480)
    depends_on: list[str] = Field(default_factory=list)
    suggested_after: list[str] = Field(default_factory=list)
    completion_criteria: str = Field(default="", max_length=2000)
    notes: str = Field(default="", max_length=4000)
    pursuit_id: UUID | None = None


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=500)
    category: Category | None = None
    status: TaskStatus | None = None
    priority: Priority | None = None
    due_date: date | None = None
    estimated_minutes: int | None = Field(default=None, ge=1, le=480)
    depends_on: list[str] | None = None
    suggested_after: list[str] | None = None
    completion_criteria: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=4000)
    pursuit_id: UUID | None = None


class BulkStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_ids: list[UUID] = Field(min_length=1, max_length=50)
    status: TaskStatus


# ---------- Helpers ----------


def _campaign_out(c: Campaign, session: Session) -> dict:
    tasks = session.scalars(select(CampaignTask).where(CampaignTask.campaign_id == c.id)).all()
    counts: dict[str, int] = {}
    for t in tasks:
        counts[t.status] = counts.get(t.status, 0) + 1
    return {
        "id": c.id,
        "campaign_key": c.campaign_key,
        "title": c.title,
        "start_date": c.start_date,
        "end_date": c.end_date,
        "timezone": c.timezone,
        "daily_capacity_minutes": c.daily_capacity_minutes,
        "preferences": c.preferences,
        "is_active": c.is_active,
        "task_counts": counts,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }


def _message_out(c: Communication | None) -> dict | None:
    """The whole imported message, never a preview: the task is acted on from this text."""
    if c is None:
        return None
    return {
        "id": c.id,
        "source": c.source,
        "channel": c.channel,
        "direction": c.direction,
        "sender": c.sender,
        "subject": c.subject,
        "body": c.body,
        "received_at": c.received_at,
        "contact_id": c.contact_id,
        "pursuit_id": c.pursuit_id,
    }


def _task_out(t: CampaignTask) -> dict:
    return {
        "id": t.id,
        "campaign_id": t.campaign_id,
        "seed_key": t.seed_key,
        "title": t.title,
        "category": t.category,
        "status": t.status,
        "priority": t.priority,
        "due_date": t.due_date,
        "estimated_minutes": t.estimated_minutes,
        "depends_on": t.depends_on,
        "suggested_after": t.suggested_after,
        "completion_criteria": t.completion_criteria,
        "notes": t.notes,
        "pursuit_id": t.pursuit_id,
        "communication_id": t.communication_id,
        "communication": _message_out(t.communication),
        "completed_at": t.completed_at,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


# ---------- Campaign endpoints ----------


@router.get("/api/campaigns")
def list_campaigns(session: Database):
    rows = session.scalars(select(Campaign).order_by(Campaign.start_date.desc())).all()
    return [_campaign_out(c, session) for c in rows]


@router.post("/api/campaigns", status_code=201)
def create_campaign(body: CampaignInput, session: Database):
    if body.end_date <= body.start_date:
        raise HTTPException(422, "end_date must be after start_date")
    row = session.scalar(select(Campaign).where(Campaign.campaign_key == body.campaign_key))
    now = datetime.now(UTC)
    if row:
        for key, value in body.model_dump(exclude={"campaign_key"}).items():
            setattr(row, key, value)
        row.updated_at = now
    else:
        row = Campaign(id=uuid4(), **body.model_dump(), created_at=now, updated_at=now)
        session.add(row)
    session.commit()
    session.refresh(row)
    return _campaign_out(row, session)


@router.get("/api/campaigns/{campaign_id}")
def read_campaign(campaign_id: UUID, session: Database):
    row = session.get(Campaign, campaign_id)
    if row is None:
        raise HTTPException(404, "Campaign not found")
    return _campaign_out(row, session)


@router.put("/api/campaigns/{campaign_id}")
def update_campaign(campaign_id: UUID, body: CampaignUpdate, session: Database):
    row = session.get(Campaign, campaign_id)
    if row is None:
        raise HTTPException(404, "Campaign not found")
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(row, key, value)
    row.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(row)
    return _campaign_out(row, session)


# ---------- Task endpoints ----------


@router.get("/api/campaigns/{campaign_id}/tasks")
def list_tasks(
    campaign_id: UUID,
    session: Database,
    status: TaskStatus | None = None,
    category: Category | None = None,
    priority: Priority | None = None,
    due_before: date | None = None,
    due_after: date | None = None,
):
    if session.get(Campaign, campaign_id) is None:
        raise HTTPException(404, "Campaign not found")
    q = select(CampaignTask).where(CampaignTask.campaign_id == campaign_id)
    if status:
        q = q.where(CampaignTask.status == status)
    if category:
        q = q.where(CampaignTask.category == category)
    if priority:
        q = q.where(CampaignTask.priority == priority)
    if due_before:
        q = q.where(CampaignTask.due_date <= due_before)
    if due_after:
        q = q.where(CampaignTask.due_date >= due_after)
    q = q.order_by(CampaignTask.due_date, CampaignTask.priority, CampaignTask.created_at)
    return [_task_out(t) for t in session.scalars(q).all()]


@router.post("/api/campaigns/{campaign_id}/tasks", status_code=201)
def create_task(campaign_id: UUID, body: TaskInput, session: Database):
    if session.get(Campaign, campaign_id) is None:
        raise HTTPException(404, "Campaign not found")
    now = datetime.now(UTC)
    task = CampaignTask(
        id=uuid4(),
        campaign_id=campaign_id,
        **body.model_dump(),
        completed_at=now if body.status == "completed" else None,
        created_at=now,
        updated_at=now,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return _task_out(task)


@router.put("/api/campaigns/{campaign_id}/tasks/{task_id}")
def update_task(campaign_id: UUID, task_id: UUID, body: TaskUpdate, session: Database):
    task = session.get(CampaignTask, task_id)
    if task is None or task.campaign_id != campaign_id:
        raise HTTPException(404, "Task not found")
    now = datetime.now(UTC)
    updates = body.model_dump(exclude_none=True)
    old_status = task.status
    for key, value in updates.items():
        setattr(task, key, value)
    if "status" in updates:
        if updates["status"] == "completed" and old_status != "completed":
            task.completed_at = now
        elif updates["status"] != "completed":
            task.completed_at = None
    task.updated_at = now
    session.commit()
    session.refresh(task)
    return _task_out(task)


@router.post("/api/campaigns/{campaign_id}/tasks/bulk-status")
def bulk_update_status(campaign_id: UUID, body: BulkStatusInput, session: Database):
    if session.get(Campaign, campaign_id) is None:
        raise HTTPException(404, "Campaign not found")
    now = datetime.now(UTC)
    updated = 0
    for tid in body.task_ids:
        task = session.get(CampaignTask, tid)
        if task and task.campaign_id == campaign_id:
            old = task.status
            task.status = body.status
            if body.status == "completed" and old != "completed":
                task.completed_at = now
            elif body.status != "completed":
                task.completed_at = None
            task.updated_at = now
            updated += 1
    session.commit()
    return {"updated": updated}


# ---------- Today endpoint ----------

PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
ACTIVE_TASK_STATUSES = {"planned", "in_progress", "waiting", "blocked"}


@router.get("/api/today")
def today_view(session: Database):
    campaign = session.scalar(select(Campaign).where(Campaign.is_active).limit(1))
    if campaign is None:
        return {
            "campaign": None,
            "priority_actions": [],
            "overdue_tasks": [],
            "today_tasks": [],
            "upcoming_tasks": [],
            "interviews": [],
            "follow_ups": [],
            "capacity": None,
            "commitments": [],
        }

    tz = ZoneInfo(campaign.timezone)
    today = datetime.now(tz).date()
    day_number = (today - campaign.start_date).days
    days_remaining = (campaign.end_date - today).days

    # Campaign tasks
    all_tasks = session.scalars(
        select(CampaignTask)
        .where(
            CampaignTask.campaign_id == campaign.id, CampaignTask.status.in_(ACTIVE_TASK_STATUSES)
        )
        .order_by(CampaignTask.priority, CampaignTask.due_date)
    ).all()

    overdue = [_task_out(t) for t in all_tasks if t.due_date and t.due_date < today]
    today_tasks = [_task_out(t) for t in all_tasks if t.due_date == today]
    upcoming_end = today + timedelta(days=3)
    upcoming = [
        _task_out(t) for t in all_tasks if t.due_date and today < t.due_date <= upcoming_end
    ]

    # Top 3 priority actions (overdue P0 first, then today P0, then overdue P1, etc.)
    priority_pool = []
    for t in all_tasks:
        if t.due_date and t.due_date <= today:
            score = PRIORITY_ORDER.get(t.priority, 3) - (10 if t.due_date < today else 0)
            reason = (
                f"Overdue since {t.due_date}" if t.due_date < today else f"{t.priority} due today"
            )
            priority_pool.append((score, t, reason))
    priority_pool.sort(key=lambda x: x[0])
    priority_actions = [
        {**_task_out(t), "priority_reason": reason} for _, t, reason in priority_pool[:3]
    ]

    # Pursuits: interviews and follow-ups
    pursuits = session.scalars(select(Pursuit).order_by(Pursuit.updated_at.desc())).all()
    interviews = []
    follow_ups = []
    commitments = []
    for p in pursuits:
        if p.stage == "interview":
            interviews.append(
                {
                    "id": str(p.id),
                    "title": p.job.get("title", ""),
                    "company": p.job.get("company", ""),
                    "next_action_on": p.next_action_on,
                    "score": p.job.get("score"),
                }
            )
        if p.stage == "offer" or p.stage == "interview":
            commitments.append(
                {
                    "id": str(p.id),
                    "title": p.job.get("title", ""),
                    "company": p.job.get("company", ""),
                    "stage": p.stage,
                    "next_action_on": p.next_action_on,
                }
            )
        if (
            p.next_action_on
            and p.next_action_on <= today
            and p.stage not in ("accepted", "rejected", "withdrawn", "dismissed")
        ):
            follow_ups.append(
                {
                    "id": str(p.id),
                    "title": p.job.get("title", ""),
                    "company": p.job.get("company", ""),
                    "stage": p.stage,
                    "next_action_on": p.next_action_on,
                }
            )

    # Capacity
    completed_today = session.scalars(
        select(CampaignTask).where(
            CampaignTask.campaign_id == campaign.id,
            CampaignTask.status == "completed",
            CampaignTask.completed_at >= datetime.now(UTC).replace(hour=0, minute=0, second=0),
        )
    ).all()
    used_minutes = sum(t.estimated_minutes or 0 for t in completed_today)

    return {
        "campaign": {
            "id": campaign.id,
            "title": campaign.title,
            "day_number": day_number,
            "days_remaining": days_remaining,
            "daily_capacity_minutes": campaign.daily_capacity_minutes,
            "timezone": campaign.timezone,
        },
        "priority_actions": priority_actions,
        "overdue_tasks": overdue[:10],
        "today_tasks": today_tasks,
        "upcoming_tasks": upcoming[:10],
        "interviews": interviews[:10],
        "follow_ups": follow_ups[:10],
        "capacity": {
            "used_minutes": used_minutes,
            "remaining_minutes": max(0, campaign.daily_capacity_minutes - used_minutes),
            "total_minutes": campaign.daily_capacity_minutes,
        },
        "commitments": commitments[:10],
    }
