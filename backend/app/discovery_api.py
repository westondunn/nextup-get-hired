import html
import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine, get_session
from app.discovery import enqueue_discovery, profile_ready
from app.employer_catalog import CATALOG, MAX_BOARDS
from app.job_identity import identity_key
from app.models import DiscoverySettings, Job, JobFetch, Profile
from app.relevance import MatchPreferences
from app.sources.common import NormalizedJob, SourceError

router = APIRouter(prefix="/api", tags=["discovery"])
Database = Annotated[Session, Depends(get_session)]
Token = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,100}$")]


class Board(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    provider: Literal["greenhouse", "lever", "ashby"]
    board: Token
    company: str = Field(min_length=1, max_length=300, pattern=r"^[^\x00]+$")


class DiscoveryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool = False
    interval_hours: int = Field(default=24, ge=6, le=168)
    min_score: int = Field(default=20, ge=0, le=100)
    boards: list[Board] = Field(default_factory=list, max_length=MAX_BOARDS)
    match_preferences: MatchPreferences = Field(default_factory=MatchPreferences)

    @model_validator(mode="after")
    def validate_boards(self):
        keys = [(b.provider, b.board.casefold()) for b in self.boards]
        if len(keys) != len(set(keys)):
            raise ValueError("Choose each employer board only once")
        if self.enabled and not self.boards:
            raise ValueError("Choose at least one employer for automatic discovery")
        return self


@router.get("/discovery")
def read_discovery(session: Database):
    config = session.get(DiscoverySettings, 1)
    settings = (
        DiscoveryInput.model_validate(
            {key: getattr(config, key) for key in DiscoveryInput.model_fields}
        )
        if config
        else DiscoveryInput()
    )
    states = []
    for board in settings.boards:
        run = session.scalar(
            select(JobFetch)
            .where(JobFetch.source == board.provider, JobFetch.board_key == board.board)
            .order_by(JobFetch.created_at.desc())
            .limit(1)
        )
        states.append(
            {
                **board.model_dump(),
                "run": {
                    "id": str(run.id),
                    "status": run.status,
                    "received": run.received_count,
                    "stored": run.stored_count,
                    "invalid": run.skipped_count,
                    "error": run.error_message,
                    "completed_at": run.completed_at,
                    "automatic": bool(run.query.get("automatic")),
                }
                if run
                else None,
            }
        )
    return {
        **settings.model_dump(),
        "catalog": CATALOG,
        "max_boards": MAX_BOARDS,
        "states": states,
        "profile_ready": profile_ready(session.get(Profile, 1)),
        "live_enabled": get_settings().live_job_fetch_enabled,
        "next_run_at": config.next_run_at if config else None,
        "last_run_at": config.last_run_at if config else None,
    }


@router.put("/discovery")
def save_discovery(body: DiscoveryInput, session: Database):
    if body.enabled and (
        not get_settings().live_job_fetch_enabled or not profile_ready(session.get(Profile, 1))
    ):
        raise HTTPException(
            409, "Automatic discovery needs live fetching enabled and a real saved profile."
        )
    # Serialize configuration changes with the scheduler/manual enqueue path.
    session.execute(insert(DiscoverySettings).values(id=1, boards=[]).on_conflict_do_nothing())
    config = session.get(DiscoverySettings, 1, with_for_update=True)
    was_enabled, old_interval = config.enabled, config.interval_hours
    for key, value in body.model_dump().items():
        if key == "match_preferences" and key not in body.model_fields_set:
            continue  # Older clients must not erase a newly configured policy.
        setattr(config, key, value)
    if not body.enabled:
        config.next_run_at = None
    elif not was_enabled or config.next_run_at is None:
        config.next_run_at = datetime.now(UTC)
    elif old_interval != body.interval_hours:
        config.next_run_at = datetime.now(UTC) + timedelta(hours=body.interval_hours)
    session.commit()
    return read_discovery(session)


@router.post("/discovery/run", status_code=202)
def run_discovery():
    try:
        runs = enqueue_discovery(get_engine())
    except SourceError as exc:
        raise HTTPException(409, exc.message) from None
    if not runs:
        raise HTTPException(409, "Selected employers are already pending or cooling down.")
    return {"runs": runs}


class JobReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=500)
    company: str = Field(min_length=1, max_length=300)
    location: str = Field(min_length=1, max_length=500)
    description: str = Field(max_length=20000)
    url: str = Field(max_length=2048)


@router.post("/job-references", status_code=201)
def save_reference(body: JobReference, session: Database):
    # Explicit metadata import, not a server-side URL fetch or an HTML scraper.
    now = datetime.now(UTC)
    try:
        job = NormalizedJob(
            **body.model_dump(),
            external_id=sha256(body.url.encode()).hexdigest(),
            posted_at=now,
            date_kind="observed",
        )
    except ValueError as exc:
        raise HTTPException(422, "Provide valid reference fields and an HTTP(S) URL.") from exc
    values = job.model_dump()
    values.update(
        source="reference",
        fetched_at=now,
        dedupe_key=identity_key("reference", job.external_id, job.company, job.title, job.location),
    )
    # A repeated import must not relabel the original observation as a new posting.
    session.execute(insert(Job).values(**values).on_conflict_do_nothing())
    session.commit()
    return {"source": "reference", "external_id": job.external_id}


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities for plain-text storage."""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|li|h[1-6]|div)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_date(val: str | None) -> datetime | None:
    """Best-effort parse of various date formats from CSV sources."""
    if not val or not val.strip():
        return None
    val = val.strip()
    # Try ISO format first
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            return (
                datetime.strptime(val, fmt).replace(tzinfo=UTC)
                if "+" not in val and "Z" not in val
                else datetime.strptime(val, fmt)
            )
        except ValueError:
            pass
    # Try JS Date format: "Mon Jan 05 2026 09:30:00 GMT+0000 (Coordinated Universal Time)"
    match = re.match(r"\w{3} (\w{3}) (\d{2}) (\d{4}) (\d{2}):(\d{2}):(\d{2})", val)
    if match:
        try:
            g = match.group
            clean = f"{g(3)}-{g(1)}-{g(2)} {g(4)}:{g(5)}:{g(6)}"
            # Use strptime with month abbreviation
            return datetime.strptime(clean, "%Y-%b-%d %H:%M:%S").replace(tzinfo=UTC)
        except (ValueError, TypeError):
            pass
    return None


class CsvJobRow(BaseModel):
    """A single job row from an external CSV import."""

    model_config = ConfigDict(extra="allow")
    source: str = ""
    title: str = ""
    company: str = ""
    location: str = ""
    url: str = ""
    external_id: str = ""
    posted_date: str = ""
    snippet: str = ""


class CsvImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[CsvJobRow]


@router.post("/job-imports/csv", status_code=201)
def import_csv_jobs(body: CsvImportRequest, session: Database):
    """Bulk import jobs from an external CSV import. Deduplicates by external_id+source."""
    now = datetime.now(UTC)
    imported = 0
    skipped = 0
    errors: list[str] = []

    for i, row in enumerate(body.rows):
        # Skip empty rows
        if not row.title.strip() or not row.url.strip():
            skipped += 1
            continue

        source_label = row.source.strip() or "csv_import"
        ext_id = row.external_id.strip() or sha256(row.url.encode()).hexdigest()
        description = _strip_html(row.snippet) if row.snippet else ""
        posted = _parse_date(row.posted_date) or now

        # Truncate fields to model limits
        raw_title = row.title.strip()
        raw_company = row.company.strip()

        # WeWorkRemotely embeds company in title as "Company: Title"
        if not raw_company and ": " in raw_title:
            parts = raw_title.split(": ", 1)
            raw_company = parts[0]
            raw_title = parts[1]

        title = raw_title[:500]
        company = raw_company[:300] or "Unknown"
        location = row.location.strip()[:500] or "Remote"
        url = row.url.strip()[:2048]

        # Validate URL
        if not url.startswith(("http://", "https://")):
            skipped += 1
            errors.append(f"Row {i}: invalid URL")
            continue

        values = {
            "source": "reference",
            "external_id": f"{source_label}:{ext_id}"[:200],
            "title": title,
            "company": company,
            "location": location,
            "description": description[:20000],
            "url": url,
            "posted_at": posted,
            "fetched_at": now,
            "date_kind": "posted",
            "dedupe_key": identity_key("reference", ext_id, company, title, location),
        }
        session.execute(insert(Job).values(**values).on_conflict_do_nothing())
        imported += 1

    session.commit()
    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors[:10],
        "total_rows": len(body.rows),
    }
