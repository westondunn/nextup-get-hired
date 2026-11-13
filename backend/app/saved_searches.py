from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import SavedSearch

router = APIRouter(prefix="/api/saved-searches", tags=["saved searches"])
Database = Annotated[Session, Depends(get_session)]
FilterText = Annotated[str, StringConstraints(max_length=160, pattern=r"^[^\x00]*$")]


class SearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    q: FilterText = ""
    company: FilterText = ""
    location: FilterText = ""
    exclude: str = Field(default="", max_length=200, pattern=r"^[^\x00]*$")
    work_mode: Literal["any", "remote", "hybrid", "onsite", "unknown"] = "any"
    min_score: int | None = Field(default=None, ge=0, le=100)
    max_age_days: int | None = Field(default=None, ge=0, le=3650)
    sort: Literal["newest", "score"] = "newest"
    discovery_only: bool = False


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=80, pattern=r"^[^\x00]+$"
        ),
    ]
    source: Literal[
        "adzuna",
        "greenhouse",
        "lever",
        "ashby",
        "reference",
        "all",
    ]
    include_expired: bool = False
    filters: SearchFilters = Field(default_factory=SearchFilters)


class SearchOut(SearchInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime
    updated_at: datetime
    alerts_enabled: bool
    alert_min_score: int
    alert_check_status: str
    alert_checked_at: datetime | None
    alert_worker: str | None


def persist(session: Session, record: SavedSearch, body: SearchInput):
    record.name = body.name
    record.name_key = " ".join(body.name.casefold().split())
    record.source = body.source
    record.include_expired = body.include_expired
    record.filters = body.filters.model_dump()
    record.updated_at = datetime.now(UTC)
    session.add(record)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="A saved search with that name already exists."
        ) from None
    session.refresh(record)
    return record


def find_record(session: Session, search_id: UUID):
    record = session.get(SavedSearch, search_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Saved search not found.")
    return record


@router.get("", response_model=list[SearchOut])
def list_searches(session: Database):
    return session.scalars(select(SavedSearch).order_by(SavedSearch.name_key, SavedSearch.id)).all()


@router.post("", response_model=SearchOut, status_code=201)
def create_search(body: SearchInput, session: Database):
    return persist(session, SavedSearch(id=uuid4()), body)


@router.get("/{search_id}", response_model=SearchOut)
def read_search(search_id: UUID, session: Database):
    return find_record(session, search_id)


@router.put("/{search_id}", response_model=SearchOut)
def replace_search(search_id: UUID, body: SearchInput, session: Database):
    return persist(session, find_record(session, search_id), body)


@router.delete("/{search_id}", status_code=204)
def delete_search(search_id: UUID, session: Database):
    session.delete(find_record(session, search_id))
    session.commit()
    return Response(status_code=204)
