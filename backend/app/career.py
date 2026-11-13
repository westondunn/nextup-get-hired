"""Local job-search planning and tracking. No application or message delivery."""

import csv
import io
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import companies, scoring
from app.application_detect import NOT_A_REPLY
from app.db import get_session
from app.discovery import profile_ready
from app.job_identity import identity_key
from app.jobs import JobOut, Source, query_jobs
from app.models import (
    CampaignTask,
    CareerSettings,
    Communication,
    DiscoverySettings,
    Job,
    Profile,
    Pursuit,
    PursuitEvent,
    ResumeVersion,
)

router = APIRouter(prefix="/api/career", tags=["career workspace"])
Database = Annotated[Session, Depends(get_session)]
Stage = Literal[
    "review",
    "preparing",
    "applied",
    "interview",
    "offer",
    "accepted",
    "rejected",
    "withdrawn",
    "dismissed",
]
CLOSED = {"accepted", "rejected", "withdrawn", "dismissed"}
ACTIONS = {
    "review": "Check fit, pay and eligibility; decide whether to pursue",
    "preparing": "Tailor your resume and draft; apply on the employer site",
    "applied": "Check for a response and prepare a follow-up",
    "interview": "Prepare examples, questions and interview logistics",
    "offer": "Review compensation, terms and your decision deadline",
}


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    automatic: bool = False
    daily_limit: int = Field(default=5, ge=1, le=20)
    follow_up_days: int = Field(default=7, ge=1, le=30)
    timezone: str = Field(default="UTC", max_length=80)
    minimum_annual_usd: int | None = Field(default=None, ge=1, le=2000000)
    minimum_hourly_usd: int | None = Field(default=None, ge=1, le=10000)
    start_by: str = Field(default="", max_length=10)
    open_to_contract: bool = False
    open_to_individual_contributor: bool = False
    verified_achievements: str = Field(default="", max_length=8000, pattern=r"^[^\x00]*$")
    application_template: str = Field(default="", max_length=4000, pattern=r"^[^\x00]*$")
    outreach_template: str = Field(default="", max_length=4000, pattern=r"^[^\x00]*$")

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Choose a valid IANA timezone") from None
        return value

    @field_validator("start_by")
    @classmethod
    def valid_date(cls, value):
        if value and date.fromisoformat(value).isoformat() != value:
            raise ValueError("Use YYYY-MM-DD")
        return value


def preferences(session):
    row = session.get(CareerSettings, 1)
    return Preferences.model_validate(row.preferences) if row else Preferences()


def local_day(prefs, now):
    return now.astimezone(ZoneInfo(prefs.timezone)).date()


def _apply_template(template, job, skill_line, achievement):
    """Replace {placeholders} in a user-defined template."""
    return (
        template.replace("{company}", job.company)
        .replace("{title}", job.title)
        .replace("{location}", job.location)
        .replace("{skills}", skill_line)
        .replace("{achievements}", achievement)
    )


def drafts(job, profile, prefs):
    skills = list(profile.skills) if profile else []
    evidence = scoring.tokens(job.title + " " + job.description)
    relevant = [s for s in skills if scoring.contains_phrase(evidence, scoring.tokens(s))]
    skill_line = (
        "Relevant skills: " + ", ".join(relevant[:6]) + "."
        if relevant
        else "[Add relevant skills you can substantiate.]"
    )
    achievement = (
        prefs.verified_achievements.strip() or "[Add a verified achievement relevant to this role.]"
    )
    if prefs.application_template.strip():
        application = _apply_template(prefs.application_template, job, skill_line, achievement)
    else:
        application = (
            f"Hello {job.company} hiring team,\n\n"
            f"I am interested in the {job.title} role.\n{skill_line}\n\n"
            f"{achievement}\n\nI would welcome a conversation about the "
            "team's needs and my fit.\n\n"
            "[Your name]"
        )
    if prefs.outreach_template.strip():
        outreach = _apply_template(prefs.outreach_template, job, skill_line, achievement)
    else:
        outreach = (
            f"Hello [contact name],\n\nI am exploring the "
            f"{job.title} opportunity at {job.company}. "
            f"{skill_line}\nCould you share the team's priorities and the best way to connect "
            "with the hiring team?\n\n[Your name]"
        )
    return application, outreach


def add_pursuit(session, job, creator, prefs, profile, now):
    key = identity_key(job.source, job.external_id, job.company, job.title, job.location)
    application, outreach = drafts(job, profile, prefs)
    snapshot = JobOut.model_validate(job).model_dump(mode="json")
    if profile:
        from app.relevance import MatchPreferences

        discovery = session.get(DiscoverySettings, 1)
        preferences = (
            MatchPreferences.model_validate(discovery.match_preferences)
            if discovery is not None
            else MatchPreferences()
        )
        from app.job_ratings import load_ratings

        snapshot["score_breakdown"] = scoring.score_job(
            job, profile, scoring.utc_day(), preferences, load_ratings(session)
        )
        snapshot["score"] = snapshot["score_breakdown"]["total"]
    pursuit_id = session.scalar(
        insert(Pursuit)
        .values(
            id=uuid4(),
            job_key=key,
            job=snapshot,
            created_by=creator,
            application_draft=application,
            outreach_draft=outreach,
            next_action_on=local_day(prefs, now),
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(constraint="pursuit_job_key")
        .returning(Pursuit.id)
    )
    if pursuit_id:
        session.add(
            PursuitEvent(
                id=uuid4(),
                pursuit_id=pursuit_id,
                created_at=now,
                message="Added to review by automatic plan"
                if creator == "automatic"
                else "Added to review by you",
            )
        )
        created = session.get(Pursuit, pursuit_id)
        companies.link_pursuit(session, created, now)
        return created, True
    return session.scalar(select(Pursuit).where(Pursuit.job_key == key)), False


def reconcile_plan(session, worker, *, automatic=True, now=None):
    """Serialize planning; never overwrite a tracked job or exceed the review backlog cap."""
    now = now or datetime.now(UTC)
    settings = session.scalar(
        select(CareerSettings).where(CareerSettings.id == 1).with_for_update(skip_locked=True)
    )
    if settings is None:
        return {"added": 0, "status": "not_configured"}
    prefs = Preferences.model_validate(settings.preferences)
    if automatic and not prefs.automatic:
        return {"added": 0, "status": "paused"}
    settings.checked_at, settings.worker = now, worker
    profile = session.get(Profile, 1)
    if not profile_ready(profile) or session.get(DiscoverySettings, 1) is None:
        settings.status = "profile_required"
        return {"added": 0, "status": settings.status}
    tracked = session.scalars(select(Pursuit)).all()
    day = local_day(prefs, now)
    added_today = sum(
        local_day(prefs, p.created_at) == day and p.created_by == "automatic" for p in tracked
    )
    backlog = sum(p.stage in ("review", "preparing") for p in tracked)
    capacity = max(0, min(prefs.daily_limit - added_today, prefs.daily_limit - backlog))
    page = query_jobs(
        session,
        source="all",
        sort="score",
        discovery_only=True,
        limit=None,
        commit_scores=False,
        hide_passed=True,  # a job you passed on is never planned for you
        hide_open_companies=True,  # never plan a job where you already applied
    )
    seen = {p.job_key for p in tracked}
    added = 0
    for job in page["items"]:
        if added >= capacity:
            break
        key = identity_key(job.source, job.external_id, job.company, job.title, job.location)
        if key in seen:
            continue
        _, created = add_pursuit(session, job, "automatic", prefs, profile, now)
        added += int(created)
        seen.add(key)
    settings.status = "ready" if page["items"] else "no_matches"
    return {"added": added, "status": settings.status}


_STAGE_WEIGHT = {
    "offer": 100,
    "interview": 80,
    "applied": 50,
    "preparing": 30,
    "review": 20,
    "accepted": 0,
    "rejected": 0,
    "withdrawn": 0,
    "dismissed": 0,
}


def _priority_score(pursuit, today):
    score = _STAGE_WEIGHT.get(pursuit.stage, 0)
    score += min(pursuit.job.get("score") or 0, 100) * 0.3
    if pursuit.next_action_on:
        overdue = (today - pursuit.next_action_on).days
        if overdue > 0:
            score += min(overdue * 5, 30)
    if pursuit.updated_at:
        stale_days = (datetime.now(UTC) - pursuit.updated_at).days
        if stale_days > 7:
            score -= min(stale_days, 20)
    return round(score)


def _priority_reason(pursuit, today):
    if pursuit.stage == "offer":
        return "Offer pending response"
    if pursuit.stage == "interview":
        return "Interview stage — high priority"
    if pursuit.next_action_on and pursuit.next_action_on <= today:
        return "Action overdue"
    if pursuit.updated_at and (datetime.now(UTC) - pursuit.updated_at).days > 7:
        return "Stale — needs attention"
    if (pursuit.job.get("score") or 0) >= 70:
        return "High match score"
    return ""


def resume_label(version) -> str | None:
    return f"{version.variant_name} v{version.version_number}" if version else None


def describe(pursuit, prefs, today):
    due = (
        pursuit.stage not in CLOSED
        and pursuit.next_action_on is not None
        and pursuit.next_action_on <= today
    )
    return {
        "id": pursuit.id,
        "job": pursuit.job,
        "stage": pursuit.stage,
        "notes": pursuit.notes,
        "application_draft": pursuit.application_draft,
        "outreach_draft": pursuit.outreach_draft,
        "next_action_on": pursuit.next_action_on,
        "created_by": pursuit.created_by,
        "version": pursuit.version,
        "applied_at": pursuit.applied_at,
        "updated_at": pursuit.updated_at,
        "due": due,
        "next_action": ACTIONS.get(pursuit.stage, "No action scheduled"),
        "follow_up_draft": (
            f"Hello [contact name],\n\nI am following up on my application for "
            f"{pursuit.job['title']} at {pursuit.job['company']}. I remain interested "
            "and would appreciate an update on next steps.\n\n[Your name]"
        )
        if pursuit.applied_at
        else "Record an application before preparing an application follow-up.",
        "priority_score": _priority_score(pursuit, today),
        "priority_reason": _priority_reason(pursuit, today),
        "prep_data": pursuit.prep_data or {},
        "offer_data": pursuit.offer_data or {},
        "resume_version_id": pursuit.resume_version_id,
        "company_id": pursuit.company_id,
        "resume_label": resume_label(pursuit.resume_version),
        "checks": [
            "Confirm the vacancy is still open on the employer site",
            "Verify location, work authorization, work mode and seniority",
            "Confirm compensation"
            + (f" meets ${prefs.minimum_annual_usd:,}/year" if prefs.minimum_annual_usd else "")
            + (f" or ${prefs.minimum_hourly_usd}/hour" if prefs.minimum_hourly_usd else ""),
            *([f"Confirm a feasible start date by {prefs.start_by}"] if prefs.start_by else []),
            *(
                ["Ask whether contract terms are available and compare benefits and hours"]
                if prefs.open_to_contract
                else []
            ),
            *(
                ["Review responsibility level; individual-contributor roles are an option"]
                if prefs.open_to_individual_contributor
                else []
            ),
            "Use only achievements and skills you can substantiate; remove draft placeholders",
        ],
    }


@router.get("")
def read_career(session: Database):
    prefs = preferences(session)
    today = local_day(prefs, datetime.now(UTC))
    rows = session.scalars(select(Pursuit).order_by(Pursuit.updated_at.desc())).all()
    priority = {"offer": 0, "interview": 1, "applied": 2, "preparing": 3, "review": 4}
    rows.sort(
        key=lambda p: (
            p.stage in CLOSED,
            (p.next_action_on or date.max) > today,
            priority.get(p.stage, 5),
            p.next_action_on or date.max,
            -(p.job.get("score") or 0),
            str(p.id),
        )
    )
    items = [describe(row, prefs, today) for row in rows]
    settings = session.get(CareerSettings, 1)
    return {
        "preferences": prefs.model_dump(),
        "today": today,
        "items": items[:200],
        "total": len(items),
        "plan": [item for item in items if item["due"]][: prefs.daily_limit],
        "counts": {stage: sum(row.stage == stage for row in rows) for stage in Stage.__args__},
        "ready": profile_ready(session.get(Profile, 1))
        and session.get(DiscoverySettings, 1) is not None,
        "automation": {
            "status": settings.status if settings else "not_configured",
            "checked_at": settings.checked_at if settings else None,
            "worker": settings.worker if settings else None,
        },
        "delivery": "local_drafts_only",
        "analytics": _compute_analytics(session, rows, today),
    }


def _compute_analytics(session: Session, pursuits: list[Pursuit], today: date) -> dict:
    counts = {}
    for p in pursuits:
        counts[p.stage] = counts.get(p.stage, 0) + 1

    # Stage transition counts from events
    events = session.scalars(
        select(PursuitEvent)
        .where(PursuitEvent.message.like("You recorded stage:%"))
        .order_by(PursuitEvent.created_at)
    ).all()

    transitions: dict[str, int] = {}
    for ev in events:
        # Parse "You recorded stage: X → Y"
        parts = ev.message.split("→")
        if len(parts) == 2:
            before = parts[0].split(":")[-1].strip()
            after = parts[1].strip()
            key = f"{before}_to_{after}"
            transitions[key] = transitions.get(key, 0) + 1

    # Conversion rates
    total = len(pursuits)
    applied = sum(1 for p in pursuits if p.stage not in ("review", "preparing", "dismissed"))
    interviewing = sum(1 for p in pursuits if p.stage in ("interview", "offer", "accepted"))
    offers = sum(1 for p in pursuits if p.stage in ("offer", "accepted"))

    # Stale items (no update in 7+ days, not closed)
    stale_cutoff = datetime.now(UTC) - timedelta(days=7)
    stale = [
        {
            "id": str(p.id),
            "title": p.job.get("title", ""),
            "company": p.job.get("company", ""),
            "stage": p.stage,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        }
        for p in pursuits
        if p.stage not in ("accepted", "rejected", "withdrawn", "dismissed")
        and p.updated_at
        and p.updated_at < stale_cutoff
    ]

    return {
        "total": total,
        "applied": applied,
        "interviewing": interviewing,
        "offers": offers,
        "apply_rate": round(applied / total * 100) if total else 0,
        "interview_rate": round(interviewing / applied * 100) if applied else 0,
        "offer_rate": round(offers / interviewing * 100) if interviewing else 0,
        "transitions": transitions,
        "stale_items": sorted(stale, key=lambda x: x["updated_at"] or "")[:10],
    }


@router.put("/preferences")
def save_preferences(body: Preferences, session: Database):
    session.execute(insert(CareerSettings).values(id=1).on_conflict_do_nothing())
    row = session.get(CareerSettings, 1, with_for_update=True)
    row.preferences = body.model_dump(mode="json")
    session.commit()
    return read_career(session)


@router.post("/plan")
def build_plan(session: Database):
    result = reconcile_plan(session, "local-request", automatic=False)
    session.commit()
    return result


class TrackInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: Source
    external_id: str = Field(min_length=1, max_length=200)
    # Set after the user confirms a second application at the same employer.
    allow_same_company: bool = False


SAME_COMPANY = "same_company"


@router.post("/pursuits")
def track(body: TrackInput, session: Database):
    job = session.get(Job, (body.source, body.external_id))
    if job is None:
        raise HTTPException(404, "Saved job not found")
    others = companies.open_company_index(session).others(job.company, job.dedupe_key)
    if others and not body.allow_same_company:
        first = others[0]
        more = f" and {len(others) - 1} more" if len(others) > 1 else ""
        raise HTTPException(
            409,
            f"You already have an open application at {first.company}: {first.title}"
            f" ({first.stage}){more}. Track this job too?",
            headers={"X-Nextup-Conflict": SAME_COMPANY},
        )
    row, created = add_pursuit(
        session, job, "manual", preferences(session), session.get(Profile, 1), datetime.now(UTC)
    )
    session.commit()
    return {"id": row.id, "created": created}


class PursuitInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: int = Field(ge=1)
    stage: Stage
    notes: str = Field(default="", max_length=12000, pattern=r"^[^\x00]*$")
    application_draft: str = Field(default="", max_length=16000, pattern=r"^[^\x00]*$")
    outreach_draft: str = Field(default="", max_length=16000, pattern=r"^[^\x00]*$")
    next_action_on: date | None = Field(default=None, strict=False)
    prep_data: dict = Field(default_factory=dict)
    offer_data: dict = Field(default_factory=dict)
    resume_version_id: UUID | None = Field(default=None, strict=False)


@router.put("/pursuits/{pursuit_id}")
def update_pursuit(pursuit_id: UUID, body: PursuitInput, session: Database):
    row = session.get(Pursuit, pursuit_id, with_for_update=True)
    if row is None:
        raise HTTPException(404, "Tracked job not found")
    if row.version != body.version:
        raise HTTPException(409, "This job changed in another view. Reload it before saving.")
    resume = None
    if body.resume_version_id is not None:
        resume = session.get(ResumeVersion, body.resume_version_id)
        if resume is None:
            raise HTTPException(404, "Resume version not found")
    resume_changed = body.resume_version_id != row.resume_version_id
    before, now = row.stage, datetime.now(UTC)
    prefs = preferences(session)
    for key, value in body.model_dump(exclude={"version"}).items():
        setattr(row, key, value)
    if body.stage == "applied" and before != "applied":
        row.applied_at = row.applied_at or now
        row.next_action_on = row.next_action_on or local_day(prefs, now) + timedelta(
            days=prefs.follow_up_days
        )
    if body.stage in CLOSED:
        row.next_action_on = None
    row.version += 1
    row.updated_at = now
    companies.link_pursuit(session, row, now)
    session.add(
        PursuitEvent(
            id=uuid4(),
            pursuit_id=row.id,
            message=f"You recorded stage: {before} → {row.stage}"
            if before != row.stage
            else (
                f"You recorded the resume submitted: {resume_label(resume)}"
                if resume_changed and resume
                else "You removed the submitted resume"
                if resume_changed
                else "You updated notes, drafts or next action"
            ),
        )
    )
    session.commit()
    return describe(row, prefs, local_day(prefs, now))


class ContactInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: int = Field(ge=1)
    note: str = Field(min_length=1, max_length=400, pattern=r"^[^\x00]+$")


@router.post("/pursuits/{pursuit_id}/contact")
def record_contact(pursuit_id: UUID, body: ContactInput, session: Database):
    row = session.get(Pursuit, pursuit_id, with_for_update=True)
    if row is None:
        raise HTTPException(404, "Tracked job not found")
    if row.version != body.version:
        raise HTTPException(409, "This job changed. Reload before recording contact.")
    if row.stage in CLOSED:
        raise HTTPException(409, "Reopen this job before scheduling a follow-up.")
    now = datetime.now(UTC)
    prefs = preferences(session)
    row.next_action_on = local_day(prefs, now) + timedelta(days=prefs.follow_up_days)
    row.updated_at, row.version = now, row.version + 1
    session.add(
        PursuitEvent(id=uuid4(), pursuit_id=row.id, message="You recorded contact: " + body.note)
    )
    session.commit()
    return describe(row, prefs, local_day(prefs, now))


class BulkItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: UUID
    version: int = Field(ge=1)


class BulkInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    items: list[BulkItem] = Field(min_length=1, max_length=50)
    stage: Stage


@router.post("/pursuits/bulk")
def bulk_update_stage(body: BulkInput, session: Database):
    now = datetime.now(UTC)
    prefs = preferences(session)
    today = local_day(prefs, now)
    succeeded, skipped = 0, 0
    for item in body.items:
        row = session.get(Pursuit, item.id, with_for_update={"skip_locked": True})
        if row is None or row.version != item.version:
            skipped += 1
            continue
        before = row.stage
        row.stage = body.stage
        if body.stage == "applied" and before != "applied":
            row.applied_at = row.applied_at or now
            row.next_action_on = row.next_action_on or today + timedelta(days=prefs.follow_up_days)
        if body.stage in CLOSED:
            row.next_action_on = None
        row.version += 1
        row.updated_at = now
        companies.link_pursuit(session, row, now)
        session.add(
            PursuitEvent(
                id=uuid4(),
                pursuit_id=row.id,
                message=f"You recorded stage: {before} → {row.stage}"
                if before != row.stage
                else "Bulk update (no stage change)",
            )
        )
        succeeded += 1
    session.commit()
    return {"succeeded": succeeded, "skipped": skipped}


@router.get("/pursuits/{pursuit_id}/events")
def read_events(pursuit_id: UUID, session: Database):
    if session.get(Pursuit, pursuit_id) is None:
        raise HTTPException(404, "Tracked job not found")
    rows = session.scalars(
        select(PursuitEvent)
        .where(PursuitEvent.pursuit_id == pursuit_id)
        .order_by(PursuitEvent.created_at.desc(), PursuitEvent.id)
        .limit(50)
    ).all()
    return [
        {
            "id": row.id,
            "message": row.message,
            "event_date": row.event_date,
            "actor": row.actor,
            "source": row.source,
            "evidence": row.evidence,
            "created_at": row.created_at,
        }
        for row in rows
    ]


class AttachmentItem(BaseModel):
    kind: str = Field(max_length=30)  # transcript, note, link, file
    label: str = Field(default="", max_length=200)
    content: str = Field(default="", max_length=50000)
    url: str = Field(default="", max_length=2048)


class TimelineEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=500)
    event_date: date
    actor: str = Field(default="", max_length=200)
    source: str = Field(default="", max_length=200)
    evidence: str = Field(default="", max_length=500)
    attachments: list[AttachmentItem] = Field(default_factory=list, max_length=10)


@router.post("/pursuits/{pursuit_id}/timeline", status_code=201)
def add_timeline_event(pursuit_id: UUID, body: TimelineEventInput, session: Database):
    """Add a backdated event to a pursuit's timeline."""
    row = session.get(Pursuit, pursuit_id)
    if row is None:
        raise HTTPException(404, "Tracked job not found")
    event = PursuitEvent(
        id=uuid4(),
        pursuit_id=pursuit_id,
        message=body.message,
        event_date=body.event_date,
        actor=body.actor,
        source=body.source,
        evidence=body.evidence,
        attachments=[a.model_dump() for a in body.attachments],
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return {
        "id": event.id,
        "message": event.message,
        "event_date": event.event_date,
        "actor": event.actor,
        "source": event.source,
        "evidence": event.evidence,
        "attachments": event.attachments,
        "created_at": event.created_at,
    }


class TimelineEventUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str | None = Field(default=None, min_length=1, max_length=500)
    event_date: date | None = None
    actor: str | None = Field(default=None, max_length=200)
    source: str | None = Field(default=None, max_length=200)
    evidence: str | None = Field(default=None, max_length=500)
    attachments: list[AttachmentItem] | None = None


@router.put("/pursuits/{pursuit_id}/timeline/{event_id}")
def update_timeline_event(
    pursuit_id: UUID, event_id: UUID, body: TimelineEventUpdate, session: Database
):
    event = session.get(PursuitEvent, event_id)
    if event is None or event.pursuit_id != pursuit_id:
        raise HTTPException(404, "Event not found")
    for key, value in body.model_dump(exclude_none=True).items():
        if key == "attachments":
            setattr(event, key, [a.model_dump() if hasattr(a, "model_dump") else a for a in value])
        else:
            setattr(event, key, value)
    session.commit()
    session.refresh(event)
    return {
        "id": event.id,
        "message": event.message,
        "event_date": event.event_date,
        "actor": event.actor,
        "source": event.source,
        "evidence": event.evidence,
        "attachments": event.attachments or [],
        "created_at": event.created_at,
    }


@router.delete("/pursuits/{pursuit_id}/timeline/{event_id}", status_code=204)
def delete_timeline_event(pursuit_id: UUID, event_id: UUID, session: Database):
    event = session.get(PursuitEvent, event_id)
    if event is None or event.pursuit_id != pursuit_id:
        raise HTTPException(404, "Event not found")
    session.delete(event)
    session.commit()


@router.get("/pursuits/{pursuit_id}/timeline")
def read_timeline(pursuit_id: UUID, session: Database):
    """Full timeline sorted by event_date (or created_at if no date)."""
    if session.get(Pursuit, pursuit_id) is None:
        raise HTTPException(404, "Tracked job not found")
    rows = session.scalars(
        select(PursuitEvent)
        .where(PursuitEvent.pursuit_id == pursuit_id)
        .order_by(
            PursuitEvent.event_date.desc().nullslast(),
            PursuitEvent.created_at.desc(),
        )
        .limit(100)
    ).all()
    return [
        {
            "id": row.id,
            "message": row.message,
            "event_date": row.event_date,
            "actor": row.actor,
            "source": row.source,
            "evidence": row.evidence,
            "attachments": row.attachments or [],
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/weekly-summary")
def weekly_summary(session: Database):
    now = datetime.now(UTC)
    this_week_start = now - timedelta(days=7)
    last_week_start = now - timedelta(days=14)

    this_week_events = session.scalars(
        select(PursuitEvent)
        .where(PursuitEvent.created_at >= this_week_start)
        .order_by(PursuitEvent.created_at)
    ).all()
    last_week_events = session.scalars(
        select(PursuitEvent).where(
            PursuitEvent.created_at >= last_week_start, PursuitEvent.created_at < this_week_start
        )
    ).all()

    def count_transitions(events, target_stage):
        return sum(1 for e in events if f"→ {target_stage}" in e.message)

    def count_added(events):
        return sum(1 for e in events if "Added to review" in e.message)

    def count_contacts(events):
        return sum(
            1
            for e in events
            if "recorded contact" in e.message.lower() or "follow-up" in e.message.lower()
        )

    return {
        "this_week": {
            "added": count_added(this_week_events),
            "applied": count_transitions(this_week_events, "applied"),
            "interviews": count_transitions(this_week_events, "interview"),
            "offers": count_transitions(this_week_events, "offer"),
            "contacts": count_contacts(this_week_events),
            "total_events": len(this_week_events),
        },
        "last_week": {
            "added": count_added(last_week_events),
            "applied": count_transitions(last_week_events, "applied"),
            "interviews": count_transitions(last_week_events, "interview"),
            "offers": count_transitions(last_week_events, "offer"),
            "contacts": count_contacts(last_week_events),
            "total_events": len(last_week_events),
        },
    }


@router.get("/activity")
def recent_activity(session: Database):
    events = session.scalars(
        select(PursuitEvent).order_by(PursuitEvent.created_at.desc()).limit(20)
    ).all()
    pursuit_ids = {e.pursuit_id for e in events}
    pursuits = (
        {p.id: p for p in session.scalars(select(Pursuit).where(Pursuit.id.in_(pursuit_ids)))}
        if pursuit_ids
        else {}
    )
    return [
        {
            "id": str(e.id),
            "message": e.message,
            "created_at": e.created_at,
            "pursuit_id": str(e.pursuit_id),
            "job_title": pursuits[e.pursuit_id].job.get("title", "")
            if e.pursuit_id in pursuits
            else "",
            "job_company": pursuits[e.pursuit_id].job.get("company", "")
            if e.pursuit_id in pursuits
            else "",
        }
        for e in events
    ]


@router.get("/metrics")
def campaign_metrics(session: Database, weeks: int = 4):
    """Cohort-based metrics with denominators per the spec (Section 8)."""
    now = datetime.now(UTC)
    pursuits = session.scalars(select(Pursuit)).all()
    all_events = session.scalars(select(PursuitEvent).order_by(PursuitEvent.created_at)).all()

    # Build per-pursuit event timeline
    pursuit_events: dict[str, list] = {}
    for ev in all_events:
        pid = str(ev.pursuit_id)
        pursuit_events.setdefault(pid, []).append(ev)

    # Weekly cohorts
    weekly: list[dict] = []
    for w in range(weeks):
        end = now - timedelta(days=w * 7)
        start = end - timedelta(days=7)
        label = f"Week {weeks - w}" if w < weeks - 1 else "This week"

        # Applications submitted in this cohort
        cohort_applied = [p for p in pursuits if p.applied_at and start <= p.applied_at < end]
        # Of those, how many reached screen/interview
        cohort_screened = [
            p
            for p in cohort_applied
            if p.stage in ("interview", "offer", "accepted")
            or any("→ interview" in ev.message for ev in pursuit_events.get(str(p.id), []))
        ]
        # Outreach in this cohort (contact events)
        cohort_contacts = [
            ev
            for ev in all_events
            if start <= ev.created_at < end and "recorded contact" in ev.message.lower()
        ]
        unique_pursuits_contacted = len({str(ev.pursuit_id) for ev in cohort_contacts})

        # Replies (inbound comms or substantive reply events)
        reply_events = [
            ev
            for ev in all_events
            if start <= ev.created_at < end
            and ("reply" in ev.message.lower() or "responded" in ev.message.lower())
        ]

        weekly.append(
            {
                "label": label,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "applications_submitted": len(cohort_applied),
                "reached_screen": len(cohort_screened),
                "screen_rate": round(len(cohort_screened) / len(cohort_applied) * 100)
                if cohort_applied
                else None,
                "outreach_threads": unique_pursuits_contacted,
                "reply_events": len(reply_events),
                "reply_rate": round(len(reply_events) / unique_pursuits_contacted * 100)
                if unique_pursuits_contacted
                else None,
            }
        )

    weekly.reverse()

    # Stage age: median days in current stage for active items
    stage_ages: dict[str, list[int]] = {}
    for p in pursuits:
        if p.stage in ("accepted", "rejected", "withdrawn", "dismissed"):
            continue
        days = (now - p.updated_at).days if p.updated_at else 0
        stage_ages.setdefault(p.stage, []).append(days)
    median_stage_age = {}
    for stage, ages in stage_ages.items():
        ages.sort()
        mid = len(ages) // 2
        median_stage_age[stage] = ages[mid] if ages else 0

    # Source performance
    source_counts: dict[str, dict] = {}
    for p in pursuits:
        src = p.job.get("source", "unknown")
        if src not in source_counts:
            source_counts[src] = {"tracked": 0, "applied": 0, "interviewing": 0, "offers": 0}
        source_counts[src]["tracked"] += 1
        if p.stage not in ("review", "preparing", "dismissed"):
            source_counts[src]["applied"] += 1
        if p.stage in ("interview", "offer", "accepted"):
            source_counts[src]["interviewing"] += 1
        if p.stage in ("offer", "accepted"):
            source_counts[src]["offers"] += 1

    # Task completion
    tasks = session.scalars(select(CampaignTask)).all()
    tasks_completed = sum(1 for t in tasks if t.status == "completed")
    tasks_total = sum(1 for t in tasks if t.status not in ("canceled",))

    return {
        "weekly_cohorts": weekly,
        "funnel": funnel(session, pursuits, pursuit_events, now, weeks),
        "median_stage_age_days": median_stage_age,
        "source_performance": source_counts,
        "tasks": {"completed": tasks_completed, "total": tasks_total},
        "notes": {
            "screen_rate": (
                "Applications reaching screen / applications in same cohort."
                " Recent cohorts may be inconclusive."
            ),
            "reply_rate": (
                "Outreach threads with substantive replies / threads initiated."
                " Automatic acknowledgments excluded."
            ),
            "unknown_is_not_zero": True,
        },
    }


INTERVIEW_STAGES = ("interview", "offer", "accepted")
OFFER_STAGES = ("offer", "accepted")


def _median(values: list[int]) -> int | None:
    if not values:
        return None
    values = sorted(values)
    return values[len(values) // 2]


def _rate(numerator: int, denominator: int) -> int | None:
    return round(numerator / denominator * 100) if denominator else None


def funnel(session, pursuits, pursuit_events, now, weeks: int) -> dict:
    """Applied → replied → interviewed → offer → accepted, from recorded events only.

    A stage counts when the pursuit sits in it now or an event recorded the transition;
    replies come from inbound mail linked to the pursuit or a recorded reply event.
    Durations use event timestamps and are unknown (not zero) when none was recorded.
    """
    inbound = session.scalars(
        select(Communication).where(
            Communication.direction == "inbound",
            Communication.status == "received",
            Communication.pursuit_id.is_not(None),
        )
    ).all()
    first_reply: dict[str, datetime] = {}
    for row in inbound:
        if (row.detection or {}).get("kind") in NOT_A_REPLY:
            continue  # a confirmation or automatic reply is not an employer response
        pid, when = str(row.pursuit_id), row.received_at or row.created_at
        if pid not in first_reply or when < first_reply[pid]:
            first_reply[pid] = when

    def first_event(pid: str, marker: str):
        return next(
            (ev.created_at for ev in pursuit_events.get(pid, []) if marker in ev.message), None
        )

    rows = []
    for p in pursuits:
        pid = str(p.id)
        replied_at = first_reply.get(pid) or first_event(pid, "Received reply")
        interview_at = first_event(pid, "→ interview")
        offer_at = first_event(pid, "→ offer")
        rows.append(
            {
                "applied_at": p.applied_at,
                "replied_at": replied_at,
                "interviewed": p.stage in INTERVIEW_STAGES or interview_at is not None,
                "interview_at": interview_at,
                "offered": p.stage in OFFER_STAGES or offer_at is not None,
                "offer_at": offer_at,
                "accepted": p.stage == "accepted" or first_event(pid, "→ accepted") is not None,
            }
        )

    def count(subset, key):
        # Reaching an interview is itself evidence of a reply, so the funnel stays ordered.
        return sum(1 for row in subset if row[key] or (key == "replied_at" and row["interviewed"]))

    applied = [row for row in rows if row["applied_at"]]
    overall = {
        "tracked": len(rows),
        "applied": len(applied),
        "replied": count(applied, "replied_at"),
        "interviewed": count(applied, "interviewed"),
        "offers": count(applied, "offered"),
        "accepted": count(applied, "accepted"),
    }
    conversion = {
        "applied_to_replied": _rate(overall["replied"], overall["applied"]),
        "replied_to_interviewed": _rate(overall["interviewed"], overall["replied"]),
        "interviewed_to_offers": _rate(overall["offers"], overall["interviewed"]),
        "applied_to_offers": _rate(overall["offers"], overall["applied"]),
    }

    def days(start, end):
        return (end - start).days if start and end and end >= start else None

    median_days = {
        "applied_to_reply": _median(
            [d for row in applied if (d := days(row["applied_at"], row["replied_at"])) is not None]
        ),
        "applied_to_interview": _median(
            [
                d
                for row in applied
                if (d := days(row["applied_at"], row["interview_at"])) is not None
            ]
        ),
        "interview_to_offer": _median(
            [d for row in applied if (d := days(row["interview_at"], row["offer_at"])) is not None]
        ),
    }
    cohorts = []
    for w in range(weeks):
        end = now - timedelta(days=w * 7)
        start = end - timedelta(days=7)
        cohort = [row for row in applied if start <= row["applied_at"] < end]
        cohorts.append(
            {
                "label": "This week" if w == 0 else f"Week {weeks - w}",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "applied": len(cohort),
                "replied": count(cohort, "replied_at"),
                "interviewed": count(cohort, "interviewed"),
                "offers": count(cohort, "offered"),
                "accepted": count(cohort, "accepted"),
            }
        )
    cohorts.reverse()
    return {
        "overall": overall,
        "conversion": conversion,
        "median_days": median_days,
        "cohorts": cohorts,
        "notes": {
            "stages": "A stage counts when the item is in it now or a timeline event recorded it.",
            "replies": "Inbound mail linked to the application, or a recorded reply event.",
            "unknown_is_not_zero": True,
        },
    }


@router.get("/export")
def export_activity(session: Database):
    """Job-search activity export as CSV."""
    pursuits = session.scalars(select(Pursuit).order_by(Pursuit.updated_at.desc())).all()
    events = session.scalars(
        select(PursuitEvent).order_by(PursuitEvent.created_at.desc()).limit(500)
    ).all()
    tasks = session.scalars(
        select(CampaignTask)
        .where(CampaignTask.status == "completed")
        .order_by(CampaignTask.completed_at.desc())
    ).all()
    comms = session.scalars(
        select(Communication)
        .where(Communication.status == "sent")
        .order_by(Communication.sent_at.desc())
    ).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Type", "Description", "Company", "Status", "Details"])

    # Pursuit activity
    for p in pursuits:
        title = p.job.get("title", "")
        company = p.job.get("company", "")
        if p.applied_at:
            writer.writerow(
                [
                    p.applied_at.strftime("%Y-%m-%d"),
                    "Application",
                    f"Applied: {title}",
                    company,
                    p.stage,
                    p.job.get("url", ""),
                ]
            )
        for ev in events:
            if ev.pursuit_id == p.id and "stage" in ev.message:
                writer.writerow(
                    [
                        ev.created_at.strftime("%Y-%m-%d"),
                        "Pipeline Update",
                        ev.message,
                        company,
                        p.stage,
                        "",
                    ]
                )

    # Completed tasks
    for t in tasks:
        writer.writerow(
            [
                t.completed_at.strftime("%Y-%m-%d") if t.completed_at else "",
                "Task",
                t.title,
                "",
                "completed",
                t.category,
            ]
        )

    # Sent communications
    for c in comms:
        writer.writerow(
            [
                c.sent_at.strftime("%Y-%m-%d") if c.sent_at else "",
                "Communication",
                c.subject or "(no subject)",
                "",
                "sent",
                c.channel,
            ]
        )

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=job-search-activity-{date.today()}.csv"
        },
    )
