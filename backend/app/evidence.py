"""Evidence bank and resume version management."""

import base64
import binascii
import re
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Annotated
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Evidence, ResumeVersion

router = APIRouter(tags=["evidence"])
Database = Annotated[Session, Depends(get_session)]


# ---------- Evidence ----------


class EvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    seed_key: str | None = Field(default=None, max_length=20)
    topic: str = Field(min_length=1, max_length=500)
    detail: str = Field(default="", max_length=8000)
    verification_status: str = Field(default="needs_user_confirmation", max_length=30)
    source: str | None = Field(default=None, max_length=300)
    scope: str | None = Field(default=None, max_length=300)
    dates: str | None = Field(default=None, max_length=100)
    personal_contribution: str = Field(default="", max_length=8000)
    permitted_wording: str = Field(default="", max_length=4000)
    instruction: str = Field(default="", max_length=2000)


class EvidenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    topic: str | None = Field(default=None, min_length=1, max_length=500)
    detail: str | None = Field(default=None, max_length=8000)
    verification_status: str | None = Field(default=None, max_length=30)
    source: str | None = None
    scope: str | None = None
    dates: str | None = None
    personal_contribution: str | None = Field(default=None, max_length=8000)
    permitted_wording: str | None = Field(default=None, max_length=4000)
    instruction: str | None = Field(default=None, max_length=2000)


def _evidence_out(e: Evidence) -> dict:
    return {
        "id": e.id,
        "seed_key": e.seed_key,
        "topic": e.topic,
        "detail": e.detail,
        "verification_status": e.verification_status,
        "source": e.source,
        "scope": e.scope,
        "dates": e.dates,
        "personal_contribution": e.personal_contribution,
        "permitted_wording": e.permitted_wording,
        "instruction": e.instruction,
        "created_at": e.created_at,
        "updated_at": e.updated_at,
    }


@router.get("/api/evidence")
def list_evidence(session: Database, verification_status: str | None = None):
    q = select(Evidence).order_by(Evidence.created_at.desc())
    if verification_status:
        q = q.where(Evidence.verification_status == verification_status)
    return [_evidence_out(e) for e in session.scalars(q).all()]


@router.post("/api/evidence", status_code=201)
def create_evidence(body: EvidenceInput, session: Database):
    now = datetime.now(UTC)
    if body.seed_key:
        existing = session.scalar(select(Evidence).where(Evidence.seed_key == body.seed_key))
        if existing:
            for key, value in body.model_dump(exclude={"seed_key"}).items():
                if value is not None and value != "":
                    setattr(existing, key, value)
            existing.updated_at = now
            session.commit()
            session.refresh(existing)
            return _evidence_out(existing)
    row = Evidence(id=uuid4(), **body.model_dump(), created_at=now, updated_at=now)
    session.add(row)
    session.commit()
    session.refresh(row)
    return _evidence_out(row)


@router.get("/api/evidence/{evidence_id}")
def read_evidence(evidence_id: UUID, session: Database):
    row = session.get(Evidence, evidence_id)
    if row is None:
        raise HTTPException(404, "Evidence not found")
    return _evidence_out(row)


@router.put("/api/evidence/{evidence_id}")
def update_evidence(evidence_id: UUID, body: EvidenceUpdate, session: Database):
    row = session.get(Evidence, evidence_id)
    if row is None:
        raise HTTPException(404, "Evidence not found")
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(row, key, value)
    row.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(row)
    return _evidence_out(row)


@router.delete("/api/evidence/{evidence_id}", status_code=204)
def delete_evidence(evidence_id: UUID, session: Database):
    row = session.get(Evidence, evidence_id)
    if row is None:
        raise HTTPException(404, "Evidence not found")
    session.delete(row)
    session.commit()


# ---------- Resumes ----------


class ResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    variant_name: str = Field(min_length=1, max_length=120)
    content: str = Field(default="", max_length=50000)
    notes: str = Field(default="", max_length=4000)


class ResumeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    content: str | None = Field(default=None, max_length=50000)
    notes: str | None = Field(default=None, max_length=4000)
    is_active: bool | None = None


# Only the two formats employers accept; the leading bytes must match the declared type.
RESUME_FILE_TYPES = {
    "application/pdf": b"%PDF-",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": b"PK\x03\x04",
}
MAX_RESUME_FILE_BYTES = 5_000_000


class ResumeFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    file_name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=100)
    data_base64: str = Field(min_length=1, max_length=7_000_000)


def safe_file_name(name: str) -> str:
    base = PurePosixPath(name.replace("\\", "/")).name
    cleaned = re.sub(r'[\x00-\x1f"]', "", base).strip() or "resume"
    return cleaned[:255]


def _resume_out(r: ResumeVersion) -> dict:
    return {
        "id": r.id,
        "variant_name": r.variant_name,
        "content": r.content,
        "version_number": r.version_number,
        "is_active": r.is_active,
        "notes": r.notes,
        "file": {
            "name": r.file_name,
            "type": r.file_type,
            "size": r.file_size,
            "uploaded_at": r.file_uploaded_at,
        }
        if r.file_name
        else None,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
    }


@router.get("/api/resumes")
def list_resumes(session: Database, is_active: bool | None = None):
    q = select(ResumeVersion).order_by(
        ResumeVersion.variant_name, ResumeVersion.version_number.desc()
    )
    if is_active is not None:
        q = q.where(ResumeVersion.is_active == is_active)
    return [_resume_out(r) for r in session.scalars(q).all()]


@router.post("/api/resumes", status_code=201)
def create_resume(body: ResumeInput, session: Database):
    max_version = session.scalar(
        select(ResumeVersion.version_number)
        .where(ResumeVersion.variant_name == body.variant_name)
        .order_by(ResumeVersion.version_number.desc())
        .limit(1)
    )
    now = datetime.now(UTC)
    row = ResumeVersion(
        id=uuid4(),
        variant_name=body.variant_name,
        content=body.content,
        version_number=(max_version or 0) + 1,
        notes=body.notes,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _resume_out(row)


@router.get("/api/resumes/{resume_id}")
def read_resume(resume_id: UUID, session: Database):
    row = session.get(ResumeVersion, resume_id)
    if row is None:
        raise HTTPException(404, "Resume not found")
    return _resume_out(row)


@router.put("/api/resumes/{resume_id}")
def update_resume(resume_id: UUID, body: ResumeUpdate, session: Database):
    row = session.get(ResumeVersion, resume_id)
    if row is None:
        raise HTTPException(404, "Resume not found")
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(row, key, value)
    row.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(row)
    return _resume_out(row)


@router.put("/api/resumes/{resume_id}/file")
def upload_resume_file(resume_id: UUID, body: ResumeFileInput, session: Database):
    row = session.get(ResumeVersion, resume_id)
    if row is None:
        raise HTTPException(404, "Resume not found")
    signature = RESUME_FILE_TYPES.get(body.content_type)
    if signature is None:
        raise HTTPException(422, "Upload a PDF or Word (.docx) file.")
    try:
        data = base64.b64decode(body.data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, "The file could not be decoded.") from exc
    if len(data) > MAX_RESUME_FILE_BYTES:
        raise HTTPException(413, "Resume files are limited to 5 MB.")
    if not data.startswith(signature):
        raise HTTPException(422, "The file contents do not match the declared type.")
    now = datetime.now(UTC)
    row.file_name = safe_file_name(body.file_name)
    row.file_type = body.content_type
    row.file_size = len(data)
    row.file_uploaded_at = now
    row.file_data = data
    row.updated_at = now
    session.commit()
    session.refresh(row)
    return _resume_out(row)


@router.get("/api/resumes/{resume_id}/file")
def download_resume_file(resume_id: UUID, session: Database):
    row = session.get(ResumeVersion, resume_id)
    if row is None or not row.file_name:
        raise HTTPException(404, "No file is stored for this resume version")
    # RFC 6266: an ASCII fallback plus the UTF-8 name for browsers that read filename*.
    fallback = row.file_name.encode("ascii", "replace").decode().replace("?", "_")
    return Response(
        content=row.file_data,
        media_type=row.file_type,
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(row.file_name)}"
            )
        },
    )


@router.delete("/api/resumes/{resume_id}/file", status_code=204)
def delete_resume_file(resume_id: UUID, session: Database):
    row = session.get(ResumeVersion, resume_id)
    if row is None:
        raise HTTPException(404, "Resume not found")
    row.file_name = row.file_type = row.file_size = row.file_uploaded_at = row.file_data = None
    row.updated_at = datetime.now(UTC)
    session.commit()


@router.post("/api/resumes/{resume_id}/new-version", status_code=201)
def new_resume_version(resume_id: UUID, session: Database):
    source = session.get(ResumeVersion, resume_id)
    if source is None:
        raise HTTPException(404, "Resume not found")
    now = datetime.now(UTC)
    row = ResumeVersion(
        id=uuid4(),
        variant_name=source.variant_name,
        content=source.content,
        version_number=source.version_number + 1,
        notes="",
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _resume_out(row)
