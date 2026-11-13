"""Follow-up rule management."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import FollowUpRule

router = APIRouter(prefix="/api/follow-up-rules", tags=["follow-up rules"])
Database = Annotated[Session, Depends(get_session)]


class RuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    rule_key: str = Field(min_length=1, max_length=60)
    trigger: str = Field(min_length=1, max_length=80)
    delay_business_days: int = Field(default=5, ge=1, le=30)
    action: str = Field(default="create_review_task", max_length=40)
    contact_required_for_outreach: bool = False
    enabled: bool = True
    config: dict = Field(default_factory=dict)


class RuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    trigger: str | None = Field(default=None, max_length=80)
    delay_business_days: int | None = Field(default=None, ge=1, le=30)
    action: str | None = Field(default=None, max_length=40)
    contact_required_for_outreach: bool | None = None
    enabled: bool | None = None
    config: dict | None = None


def _rule_out(r: FollowUpRule) -> dict:
    return {
        "id": r.id,
        "rule_key": r.rule_key,
        "trigger": r.trigger,
        "delay_business_days": r.delay_business_days,
        "action": r.action,
        "contact_required_for_outreach": r.contact_required_for_outreach,
        "enabled": r.enabled,
        "config": r.config,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
    }


@router.get("")
def list_rules(session: Database):
    return [
        _rule_out(r)
        for r in session.scalars(select(FollowUpRule).order_by(FollowUpRule.rule_key)).all()
    ]


@router.post("", status_code=201)
def create_rule(body: RuleInput, session: Database):
    now = datetime.now(UTC)
    existing = session.scalar(select(FollowUpRule).where(FollowUpRule.rule_key == body.rule_key))
    if existing:
        for key, value in body.model_dump(exclude={"rule_key"}).items():
            setattr(existing, key, value)
        existing.updated_at = now
        session.commit()
        session.refresh(existing)
        return _rule_out(existing)
    row = FollowUpRule(id=uuid4(), **body.model_dump(), created_at=now, updated_at=now)
    session.add(row)
    session.commit()
    session.refresh(row)
    return _rule_out(row)


@router.put("/{rule_id}")
def update_rule(rule_id: UUID, body: RuleUpdate, session: Database):
    row = session.get(FollowUpRule, rule_id)
    if row is None:
        raise HTTPException(404, "Rule not found")
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(row, key, value)
    row.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(row)
    return _rule_out(row)


@router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: UUID, session: Database):
    row = session.get(FollowUpRule, rule_id)
    if row is None:
        raise HTTPException(404, "Rule not found")
    session.delete(row)
    session.commit()
