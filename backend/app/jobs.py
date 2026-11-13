from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import scoring
from app.config import get_settings
from app.db import get_session
from app.job_tasks import FIXTURE_GREENHOUSE_BOARD, FIXTURE_GREENHOUSE_COMPANY, fetch_jobs
from app.models import DiscoverySettings, Job, JobFetch, Profile

router = APIRouter(prefix="/api", tags=["jobs"])
Database = Annotated[Session, Depends(get_session)]
Source = Literal["adzuna", "greenhouse", "lever", "ashby", "reference"]
SourceView = Literal[
    "adzuna",
    "greenhouse",
    "lever",
    "ashby",
    "reference",
    "all",
]


class FetchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["adzuna", "greenhouse"]


class FetchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source: Source
    status: Literal["queued", "running", "succeeded", "failed", "publish_failed"]
    query: dict
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    worker: str | None
    received_count: int
    stored_count: int
    skipped_count: int
    error_code: str | None
    error_message: str | None
    recovery_deadline: datetime | None = None
    delivery_attempts: int = 0


class JobOrigin(BaseModel):
    source: Source
    external_id: str
    url: str
    fetched_at: datetime
    expired: bool
    score: int | None = None


class ScoreComponent(BaseModel):
    key: str
    label: str
    points: int
    maximum: int
    evidence: list[str]


class ScoreExplanation(BaseModel):
    total: int = Field(ge=0, le=100)
    components: list[ScoreComponent]
    version: str
    as_of: str


class OpenApplicationOut(BaseModel):
    """An open application at this job's employer; ``same_job`` when it is this job."""

    pursuit_id: UUID
    title: str
    company: str
    stage: str
    same_job: bool


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    source: Source
    external_id: str
    title: str
    company: str
    location: str
    description: str
    url: str
    posted_at: datetime
    fetched_at: datetime
    date_kind: Literal["posted", "updated", "observed"] = "posted"
    expired: bool = False
    origins: list[JobOrigin] = Field(default_factory=list)
    score: int | None = None
    score_breakdown: ScoreExplanation | None = None
    work_modes: list[str] = Field(default_factory=list)
    # Your "more like this" (1) / "less like this" (-1) rating for this posting, if any.
    rating: int | None = None
    open_applications: list[OpenApplicationOut] = Field(default_factory=list)


class JobPage(BaseModel):
    items: list[JobOut]
    total: int
    raw_total: int
    retention_days: int
    scoring_available: bool
    scoring_version: str
    summary: dict


@router.get("/job-source")
def source_status(session: Database, source: Literal["adzuna", "greenhouse"] = "adzuna"):
    settings = get_settings()
    if settings.fixture_data_mode:
        return fixture_source_status(session, source)
    if source == "greenhouse":
        configured = bool(
            settings.greenhouse_board_token and settings.greenhouse_company_name.strip()
        )
        if not settings.live_job_fetch_enabled:
            message = "Live fetching is disabled. See the README to connect Greenhouse."
        elif not configured:
            message = "Greenhouse needs a board token and company name in local configuration."
        else:
            message = (
                "Greenhouse is ready. Fetching reads all published posts from the board below."
            )
        return {
            "ready": settings.live_job_fetch_enabled and configured,
            "message": message,
            "query": {
                "board": settings.greenhouse_board_token,
                "company": settings.greenhouse_company_name,
            }
            if configured
            else None,
        }
    configured = bool(
        settings.adzuna_app_id.get_secret_value() and settings.adzuna_app_key.get_secret_value()
    )
    profile = session.get(Profile, 1)
    ready = settings.live_job_fetch_enabled and configured and profile is not None
    if not settings.live_job_fetch_enabled:
        message = "Live fetching is disabled. See the README to connect Adzuna."
    elif not configured:
        message = "Adzuna needs an app ID and API key in local configuration."
    elif profile is None:
        message = "Save a search profile before fetching live jobs."
    else:
        message = "Adzuna is ready. Fetching sends the search below to Adzuna."
    return {
        "ready": ready,
        "message": message,
        "query": {"what": profile.target_titles[0], "where": profile.location} if profile else None,
    }


def fixture_source_status(session, source):
    """Fixture data mode (ci/test only): the bundled synthetic fixtures stand in for the
    provider. No credentials and no live switch are involved, and the worker never makes an
    external request (app.job_tasks.fixture_listings, app.sources.common)."""
    message = "Synthetic fixture data mode: no external request is made."
    if source == "greenhouse":
        query = {"board": FIXTURE_GREENHOUSE_BOARD, "company": FIXTURE_GREENHOUSE_COMPANY}
        return {"ready": True, "message": message, "query": query}
    profile = session.get(Profile, 1)
    if profile is None:
        return {"ready": False, "message": "Save a search profile before fetching.", "query": None}
    query = {"what": profile.target_titles[0], "where": profile.location}
    return {"ready": True, "message": message, "query": query}


@router.post("/job-fetches", response_model=FetchOut, status_code=202)
def start_fetch(body: FetchInput, session: Database):
    from app.recovery import new_intent

    if body.source in ("adzuna", "greenhouse"):
        status = source_status(session, body.source)
        if not status["ready"]:
            raise HTTPException(status_code=409, detail=status["message"])
        query = status["query"]
    else:
        query = {"what": "Manager", "where": "Example City"}

    previous = session.scalar(
        select(JobFetch)
        .where(JobFetch.source == body.source, JobFetch.board_key == "")
        .order_by(JobFetch.created_at.desc())
        .limit(1)
    )
    if previous and (
        previous.status in ("queued", "running")
        or (previous.status == "publish_failed" and previous.recovery_deadline is not None)
    ):
        raise HTTPException(status_code=409, detail="A fetch from this source is already pending.")
    if body.source in ("adzuna", "greenhouse") and previous:
        remaining = (
            get_settings().job_fetch_min_interval_seconds
            - (datetime.now(UTC) - previous.created_at).total_seconds()
        )
        if remaining > 0:
            raise HTTPException(
                status_code=429,
                detail="Wait before fetching again.",
                headers={"Retry-After": str(int(remaining) + 1)},
            )
    run = JobFetch(id=uuid4(), source=body.source, status="queued", query=query, **new_intent())
    session.add(run)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="A fetch from this source is already pending."
        ) from None
    session.refresh(run)
    response = FetchOut.model_validate(run)
    try:
        fetch_jobs.apply_async(task_id=str(run.id), retry=False)
    except Exception:
        session.execute(
            update(JobFetch)
            .where(JobFetch.id == run.id, JobFetch.status == "queued")
            .values(
                status="publish_failed",
                error_code="broker_unavailable",
                error_message="Delivery unconfirmed; automatic recovery is pending.",
            )
        )
        session.commit()
        raise HTTPException(
            status_code=503,
            detail="Delivery unconfirmed; automatic recovery is pending. Do not resubmit.",
        ) from None
    return response


@router.get("/job-fetches/latest", response_model=FetchOut | None)
def latest_fetch(session: Database, source: Source = "adzuna"):
    return session.scalar(
        select(JobFetch)
        .where(JobFetch.source == source, JobFetch.board_key == "")
        .order_by(JobFetch.created_at.desc())
        .limit(1)
    )


@router.get("/job-fetches/{run_id}", response_model=FetchOut)
def get_fetch(run_id: UUID, session: Database):
    run = session.get(JobFetch, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Fetch not found")
    return run


@router.get("/jobs", response_model=JobPage)
def list_jobs(
    session: Database,
    source: SourceView = "adzuna",
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_expired: bool = False,
    q: Annotated[str, Query(max_length=160)] = "",
    company: Annotated[str, Query(max_length=160)] = "",
    location: Annotated[str, Query(max_length=160)] = "",
    exclude: Annotated[str, Query(max_length=200)] = "",
    work_mode: Literal["any", "remote", "hybrid", "onsite", "unknown"] = "any",
    min_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    max_age_days: Annotated[int | None, Query(ge=0, le=3650)] = None,
    sort: Literal["newest", "score"] = "newest",
    discovery_only: bool = False,
    hide_passed: bool = False,
    hide_open_companies: bool = False,
):
    return query_jobs(
        session,
        source=source,
        limit=limit,
        offset=offset,
        include_expired=include_expired,
        q=q,
        company=company,
        location=location,
        exclude=exclude,
        work_mode=work_mode,
        min_score=min_score,
        max_age_days=max_age_days,
        sort=sort,
        discovery_only=discovery_only,
        hide_passed=hide_passed,
        hide_open_companies=hide_open_companies,
    )


def query_jobs(
    session: Session,
    *,
    source="adzuna",
    limit=10,
    offset=0,
    include_expired=False,
    q="",
    company="",
    location="",
    exclude="",
    work_mode="any",
    min_score=None,
    max_age_days=None,
    sort="newest",
    discovery_only=False,
    commit_scores=True,
    hide_passed=False,
    hide_open_companies=False,
):
    """Shared listing semantics; workers own their surrounding transaction."""
    profile = session.get(Profile, 1)
    from app.relevance import MatchPreferences

    discovery = session.get(DiscoverySettings, 1)
    # Eligibility and responsibility scoring read the same preferences as discovery.
    preferences = (
        MatchPreferences.model_validate(discovery.match_preferences)
        if discovery is not None
        else MatchPreferences()
    )
    if discovery_only:
        from app.discovery import matches_profile, profile_ready

        if discovery is None or not profile_ready(profile):
            raise HTTPException(409, "Save a real profile and discovery settings before matching.")
    if profile is None and (min_score is not None or sort == "score"):
        raise HTTPException(
            status_code=409, detail="Save a search profile before scoring or filtering by score."
        )
    today = scoring.utc_day()
    from app.job_ratings import load_ratings, ratings_by_key

    ratings = load_ratings(session)
    rated = ratings_by_key(session)
    from app.companies import open_company_index

    open_index = open_company_index(session)
    sources = {
        "all": ["adzuna", "greenhouse", "lever", "ashby", "reference"],
    }.get(source, [source])
    retention = get_settings().job_retention_days
    cutoff = datetime.now(UTC) - timedelta(days=retention)
    query = select(Job).where(Job.source.in_(sources))
    if not include_expired:
        query = query.where(Job.fetched_at > cutoff)
    records = session.scalars(
        query.order_by(Job.posted_at.desc(), Job.source, Job.external_id)
    ).all()
    groups = {}
    scores_changed = False
    for job in records:
        if profile is not None:
            signature = scoring.cache_signature(job, profile, today, preferences, ratings)
            if job.score_signature != signature or job.score is None or job.score_breakdown is None:
                job.score_breakdown = scoring.score_job(job, profile, today, preferences, ratings)
                job.score = job.score_breakdown["total"]
                job.score_signature = signature
                scores_changed = True
        key = job.dedupe_key if source == "all" else (job.source, job.external_id)
        groups.setdefault(key, []).append(job)
    items = []
    raw_total = 0
    for group in groups.values():
        if hide_passed and rated.get(group[0].dedupe_key) == -1:
            continue
        # Live, not stored: closing the application brings the employer's jobs back.
        open_here = open_index.lookup(group[0].company)
        if hide_open_companies and open_here:
            continue
        matching = [
            job
            for job in group
            if (
                not discovery_only
                or matches_profile(job, profile, discovery.min_score, preferences, ratings)
            )
            and scoring.matches_filters(
                job,
                q=q,
                company=company,
                location=location,
                exclude=exclude,
                work_mode=work_mode,
                min_score=min_score,
                max_age_days=max_age_days,
                today=today,
            )
        ]
        if not matching:
            continue
        # Explain one actual matching source record; never sum duplicate scores.
        matching.sort(
            key=lambda job: (
                job.fetched_at > cutoff,
                (job.score or 0) if profile is not None else 0,
                job.fetched_at,
                job.source,
                job.external_id,
            ),
            reverse=True,
        )
        group.sort(key=lambda job: (job.fetched_at, job.source, job.external_id), reverse=True)
        item = JobOut.model_validate(matching[0])
        item.expired = matching[0].fetched_at <= cutoff
        item.work_modes = scoring.work_modes(matching[0])
        item.rating = rated.get(matching[0].dedupe_key)
        item.open_applications = [
            OpenApplicationOut(
                pursuit_id=entry.pursuit_id,
                title=entry.title,
                company=entry.company,
                stage=entry.stage,
                same_job=entry.job_key == matching[0].dedupe_key,
            )
            for entry in open_here
        ]
        if profile is None:
            item.score, item.score_breakdown = None, None
        item.origins = [
            JobOrigin(
                source=job.source,
                external_id=job.external_id,
                url=job.url,
                fetched_at=job.fetched_at,
                expired=job.fetched_at <= cutoff,
                score=job.score if profile is not None else None,
            )
            for job in group
        ]
        items.append(item)
        raw_total += len(group)
    items.sort(
        key=lambda job: (
            (job.score or 0) if sort == "score" else 0,
            job.posted_at,
            job.source,
            job.external_id,
        ),
        reverse=True,
    )
    if scores_changed and commit_scores:
        session.commit()
    scores = [item.score for item in items if item.score is not None]
    source_counts = {
        origin_source: sum(
            origin.source == origin_source for item in items for origin in item.origins
        )
        for origin_source in sources
    }
    return {
        "items": items[offset : offset + limit if limit is not None else None],
        "total": len(items),
        "raw_total": raw_total,
        "retention_days": retention,
        "scoring_available": profile is not None,
        "scoring_version": scoring.VERSION,
        "summary": {
            "results": len(items),
            "source_records": raw_total,
            "high_score_results": sum(score >= 70 for score in scores) if profile else None,
            "average_score": round(sum(scores) / len(scores), 1) if scores else None,
            "expired_results": sum(item.expired for item in items),
            "source_counts": source_counts,
        },
    }
