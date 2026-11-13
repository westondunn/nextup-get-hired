"""Explicit, bounded cleanup of completed history. Never schedule deletion."""

import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import DiagnosticRun, JobFetch

router = APIRouter(prefix="/api/task-history", tags=["task history"])
Database = Annotated[Session, Depends(get_session)]
Policy = Annotated[Settings, Depends(get_settings)]
MODELS = {"diagnostics": DiagnosticRun, "fetches": JobFetch}
PREVIEW_LIFETIME = timedelta(minutes=10)


@lru_cache
def signing_key() -> bytes:
    # Local single-process API: restart deliberately invalidates outstanding previews.
    return secrets.token_bytes(32)


def now() -> datetime:
    return datetime.now(UTC)


def eligible(model, cutoff):
    partitions = (model.source, model.board_key) if model is JobFetch else (model.source,)
    ranked = select(
        model.id,
        func.row_number()
        .over(partition_by=partitions, order_by=(model.created_at.desc(), model.id.desc()))
        .label("position"),
    ).subquery()
    keep = select(ranked.c.id).where(ranked.c.position == 1)
    conditions = [
        model.status.in_(("succeeded", "failed")),
        model.completed_at < cutoff,
        model.id.not_in(keep),
    ]
    if model is JobFetch:
        conditions.extend((model.execution_token.is_(None), model.lease_expires_at.is_(None)))
    return select(model).where(*conditions)


def sign(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    signature = hmac.new(signing_key(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def verify(token: str, policy: Settings) -> dict:
    try:
        body, signature = token.rsplit(".", 1)
        expected = hmac.new(signing_key(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        payload = json.loads(base64.b64decode(body, altchars=b"-_", validate=True))
        if (
            payload["version"] != 1
            or payload["days"] != policy.task_history_retention_days
            or payload["batch"] != policy.task_history_batch_size
            or datetime.fromisoformat(payload["expires_at"]) <= now()
        ):
            raise ValueError("stale")
        return payload
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(409, "Preview is invalid or expired. Preview cleanup again.") from exc


@router.get("/preview")
def preview(session: Database, policy: Policy):
    timestamp = now()
    cutoff = timestamp - timedelta(days=policy.task_history_retention_days)
    expires_at = timestamp + PREVIEW_LIFETIME
    groups = {}
    ids = {}
    for name, model in MODELS.items():
        statement = eligible(model, cutoff)
        total = session.scalar(select(func.count()).select_from(statement.subquery()))
        rows = session.scalars(
            statement.order_by(model.completed_at, model.id).limit(policy.task_history_batch_size)
        ).all()
        ids[name] = [str(row.id) for row in rows]
        groups[name] = {
            "eligible": total,
            "selected": len(rows),
            "items": [
                {
                    "id": str(row.id),
                    "source": row.source,
                    "status": row.status,
                    "completed_at": row.completed_at,
                }
                for row in rows
            ],
        }
    token = sign(
        {
            "version": 1,
            "days": policy.task_history_retention_days,
            "batch": policy.task_history_batch_size,
            "cutoff": cutoff.isoformat(),
            "expires_at": expires_at.isoformat(),
            "ids": ids,
        }
    )
    return {
        "enabled": policy.task_history_cleanup_enabled,
        "retention_days": policy.task_history_retention_days,
        "batch_size": policy.task_history_batch_size,
        "cutoff": cutoff,
        "expires_at": expires_at,
        "groups": groups,
        "token": token,
    }


class CleanupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=131072)
    confirmation: Literal["delete_completed_task_history"]


@router.post("/cleanup")
def cleanup(body: CleanupRequest, session: Database, policy: Policy):
    if not policy.task_history_cleanup_enabled:
        raise HTTPException(403, "Task-history cleanup is disabled in local configuration.")
    payload = verify(body.token, policy)
    cutoff = datetime.fromisoformat(payload["cutoff"])
    result = {}
    # Recheck the exact previewed IDs under locks. Concurrent work is skipped,
    # never waited on; both tables commit atomically. Replays cannot widen the set.
    with session.begin():
        for name, model in MODELS.items():
            ids = [UUID(value) for value in payload["ids"][name]]
            rows = session.scalars(
                eligible(model, cutoff)
                .where(model.id.in_(ids))
                .order_by(model.id)
                .with_for_update(skip_locked=True, of=model)
            ).all()
            for row in rows:
                session.delete(row)
            result[name] = {"deleted": len(rows), "skipped": len(ids) - len(rows)}
    return {"groups": result}
