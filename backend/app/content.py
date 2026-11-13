"""Content calendar management."""

from datetime import UTC, date, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_session
from app.models import CampaignTask, ContentItem

router = APIRouter(prefix="/api/content", tags=["content"])
Database = Annotated[Session, Depends(get_session)]

Kind = Literal["linkedin_post", "article", "comment", "other"]
State = Literal["idea", "outline", "draft", "approved", "scheduled", "published"]
STATE_ORDER = ["idea", "outline", "draft", "approved", "scheduled", "published"]


class ContentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    seed_key: str | None = Field(default=None, max_length=20)
    kind: Kind = "linkedin_post"
    state: State = "idea"
    topic: str = Field(min_length=1, max_length=500)
    title: str | None = Field(default=None, max_length=500)
    body: str = Field(default="", max_length=20000)
    outline: list[str] | None = None
    campaign_task_id: UUID | None = None
    notes: str = Field(default="", max_length=4000)
    target_date: date | None = None
    series: str | None = Field(default=None, max_length=80)


class ContentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Kind | None = None
    state: State | None = None
    topic: str | None = Field(default=None, min_length=1, max_length=500)
    title: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, max_length=20000)
    outline: list[str] | None = None
    campaign_task_id: UUID | None = None
    published_at: datetime | None = None
    public_url: str | None = Field(default=None, max_length=2048)
    notes: str | None = Field(default=None, max_length=4000)
    target_date: date | None = None
    series: str | None = Field(default=None, max_length=80)


def _content_out(c: ContentItem) -> dict:
    task: CampaignTask | None = getattr(c, "campaign_task", None)
    linked_task = None
    if task:
        linked_task = {
            "id": str(task.id),
            "title": task.title,
            "status": task.status,
            "due_date": str(task.due_date) if task.due_date else None,
        }
    elif c.campaign_task_id:
        linked_task = {"id": str(c.campaign_task_id)}
    return {
        "id": c.id,
        "seed_key": c.seed_key,
        "kind": c.kind,
        "state": c.state,
        "topic": c.topic,
        "title": c.title,
        "body": c.body,
        "outline": c.outline,
        "campaign_task_id": c.campaign_task_id,
        "published_at": c.published_at,
        "public_url": c.public_url,
        "notes": c.notes,
        "target_date": c.target_date,
        "series": c.series,
        "linked_task": linked_task,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }


def _with_task_load(q):
    return q.options(selectinload(ContentItem.campaign_task))


@router.get("")
def list_content(
    session: Database,
    kind: Kind | None = None,
    state: State | None = None,
    series: str | None = None,
):
    q = _with_task_load(select(ContentItem)).order_by(ContentItem.created_at.desc())
    if kind:
        q = q.where(ContentItem.kind == kind)
    if state:
        q = q.where(ContentItem.state == state)
    if series:
        q = q.where(ContentItem.series == series)
    return [_content_out(c) for c in session.scalars(q).all()]


@router.post("", status_code=201)
def create_content(body: ContentInput, session: Database):
    now = datetime.now(UTC)
    if body.seed_key:
        existing = session.scalar(select(ContentItem).where(ContentItem.seed_key == body.seed_key))
        if existing:
            for key, value in body.model_dump(exclude={"seed_key"}).items():
                if value is not None and value != "":
                    setattr(existing, key, value)
            existing.updated_at = now
            session.commit()
            session.refresh(existing)
            return _content_out(existing)
    row = ContentItem(id=uuid4(), **body.model_dump(), created_at=now, updated_at=now)
    session.add(row)
    session.commit()
    session.refresh(row)
    return _content_out(row)


@router.get("/{content_id}")
def read_content(content_id: UUID, session: Database):
    row = session.scalar(_with_task_load(select(ContentItem).where(ContentItem.id == content_id)))
    if row is None:
        raise HTTPException(404, "Content not found")
    return _content_out(row)


@router.put("/{content_id}")
def update_content(content_id: UUID, body: ContentUpdate, session: Database):
    row = session.get(ContentItem, content_id)
    if row is None:
        raise HTTPException(404, "Content not found")
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(row, key, value)
    if body.state == "published" and not row.published_at:
        row.published_at = datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(row)
    return _content_out(row)


@router.delete("/{content_id}", status_code=204)
def delete_content(content_id: UUID, session: Database):
    row = session.get(ContentItem, content_id)
    if row is None:
        raise HTTPException(404, "Content not found")
    session.delete(row)
    session.commit()


@router.post("/{content_id}/advance")
def advance_content(content_id: UUID, session: Database):
    row = session.get(ContentItem, content_id)
    if row is None:
        raise HTTPException(404, "Content not found")
    idx = STATE_ORDER.index(row.state) if row.state in STATE_ORDER else -1
    if idx < 0 or idx >= len(STATE_ORDER) - 1:
        raise HTTPException(422, f"Cannot advance from {row.state}")
    row.state = STATE_ORDER[idx + 1]
    if row.state == "published" and not row.published_at:
        row.published_at = datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(row)
    return _content_out(row)
