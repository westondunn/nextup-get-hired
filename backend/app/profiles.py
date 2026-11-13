from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Profile

router = APIRouter(prefix="/api/profile", tags=["profile"])
Skill = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100, pattern=r"^[^\x00]+$"),
]
Title = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120, pattern=r"^[^\x00]+$"),
]
Location = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=160, pattern=r"^[^\x00]+$"),
]


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, from_attributes=True)

    skills: list[Skill] = Field(min_length=1, max_length=50)
    target_titles: list[Title] = Field(min_length=1, max_length=20)
    location: Location
    work_preferences: list[Literal["remote", "hybrid", "onsite"]] = Field(
        min_length=1, max_length=3
    )

    @field_validator("skills", "target_titles", "work_preferences")
    @classmethod
    def deduplicate(cls, values: list[str]) -> list[str]:
        seen = set()
        result = []
        for value in values:
            key = value.casefold()
            if key not in seen:
                result.append(value)
                seen.add(key)
        return result


@router.get("", response_model=ProfileInput)
def read_profile(session: Annotated[Session, Depends(get_session)]):
    profile = session.get(Profile, 1)
    if profile is None:
        raise HTTPException(status_code=404, detail="No profile saved yet")
    return profile


@router.put("", response_model=ProfileInput)
def save_profile(profile: ProfileInput, session: Annotated[Session, Depends(get_session)]):
    """Atomically replace the single local profile; return only the importable fields."""
    fields = profile.model_dump()
    statement = (
        insert(Profile)
        .values(id=1, **fields)
        .on_conflict_do_update(
            index_elements=[Profile.id], set_={**fields, "updated_at": func.now()}
        )
        .returning(Profile)
    )
    saved = ProfileInput.model_validate(session.scalar(statement))
    session.commit()
    return saved
