"""Rate jobs "more like this" or "less like this" to tune scoring, discovery and the plan.

Ratings feed ``scoring.ratings_component``: similar jobs gain or lose up to 15 points,
which reorders the board, changes which discovered jobs clear the minimum score at
the next ingest, and changes what the automatic plan picks. Jobs you passed on are
never added to the plan. Everything stays local.
"""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import scoring
from app.db import get_session
from app.models import Job, JobRating

router = APIRouter(prefix="/api/job-ratings", tags=["jobs"])
Database = Annotated[Session, Depends(get_session)]


def load_ratings(session: Session) -> tuple[scoring.RatedJob, ...]:
    return tuple(
        scoring.RatedJob(title=row.title, company=row.company, rating=row.rating)
        for row in session.scalars(select(JobRating).order_by(JobRating.job_key)).all()
    )


def ratings_by_key(session: Session) -> dict[str, int]:
    return dict(session.execute(select(JobRating.job_key, JobRating.rating)).all())


def _out(row: JobRating) -> dict:
    return {
        "job_key": row.job_key,
        "source": row.source,
        "external_id": row.external_id,
        "title": row.title,
        "company": row.company,
        "rating": row.rating,
        "updated_at": row.updated_at,
    }


@router.get("")
def list_ratings(session: Database):
    rows = session.scalars(select(JobRating).order_by(JobRating.updated_at.desc())).all()
    return [_out(row) for row in rows]


class RatingInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: str = Field(min_length=1, max_length=20)
    external_id: str = Field(min_length=1, max_length=200)
    # 1 = more like this, -1 = less like this, 0 = clear the rating.
    rating: Literal[-1, 0, 1]


@router.put("")
def rate_job(body: RatingInput, session: Database):
    job = session.get(Job, (body.source, body.external_id))
    if job is None:
        raise HTTPException(404, "Saved job not found")
    if body.rating == 0:
        session.execute(delete(JobRating).where(JobRating.job_key == job.dedupe_key))
        session.commit()
        return {"job_key": job.dedupe_key, "rating": 0}
    now = datetime.now(UTC)
    values = dict(
        source=job.source,
        external_id=job.external_id,
        title=job.title,
        company=job.company,
        rating=body.rating,
        updated_at=now,
    )
    session.execute(
        insert(JobRating)
        .values(id=uuid4(), job_key=job.dedupe_key, created_at=now, **values)
        .on_conflict_do_update(constraint="job_rating_job_key", set_=values)
    )
    session.commit()
    return {"job_key": job.dedupe_key, "rating": body.rating}


@router.delete("/{job_key}", status_code=204)
def clear_rating(job_key: str, session: Database):
    """Clear a rating from the list, even after its job has expired from the board."""
    deleted = session.execute(delete(JobRating).where(JobRating.job_key == job_key))
    if not deleted.rowcount:
        raise HTTPException(404, "Rating not found")
    session.commit()
