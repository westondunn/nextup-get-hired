"""Turn imported mail into tracked work.

A confirmation creates (or advances to ``applied``) the matching application, links
the message, makes sure the sender exists as a contact, and schedules the follow-up
date; the ``application_review`` rule then raises the status-check task. The same
path lets the user start an application from any received message, such as a
recruiter's first contact. Rejections and interview invitations only *suggest* a
stage; the user confirms or ignores each one. Everything created here can be undone
from the message. Nothing is sent.
"""

import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import application_detect, companies
from app.career import local_day, preferences
from app.db import get_session
from app.job_identity import identity_key
from app.models import (
    Campaign,
    CampaignTask,
    Communication,
    Contact,
    CorrespondenceSyncSettings,
    FollowUpRule,
    Pursuit,
    PursuitEvent,
)

router = APIRouter(tags=["contacts"])
Database = Annotated[Session, Depends(get_session)]

CREATOR = "email"
APPLICATION_REVIEW_RULE = "application_review"
OPEN_STAGES = ("review", "preparing", "applied", "interview", "offer")
BEFORE_APPLIED = ("review", "preparing")
# Mailboxes nobody reads: the contact is kept for the record but flagged do-not-contact.
_AUTOMATED_MAILBOX = re.compile(
    r"^[^@]*(no[-_.]?reply|do[-_.]?not[-_.]?reply|notification|career|talent|recruit"
    r"|hiring|mailer|\+email\+)[^@]*(@|$)"
    r"|^([^@]*[._+-])?jobs([._+-][^@]*)?(@|$)"
    r"|@([\w-]+\.)*(icims|greenhouse|greenhouse-mail|lever|ashbyhq|workday|myworkday"
    r"|myworkdayjobs|smartrecruiters|jobvite|taleo|successfactors)\.",
    re.I,
)


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


def _same(left: str, right: str, minimum: int) -> bool:
    left, right = _normalize(left), _normalize(right)
    if not left or not right:
        return False
    if left == right:
        return True
    return min(len(left), len(right)) >= minimum and (left in right or right in left)


def match_pursuit(
    pursuits: list[Pursuit], company: str, title: str, requisition: str = ""
) -> Pursuit | None:
    """An open application for the same employer and role, exact matches first."""
    best, best_rank = None, 0
    for pursuit in pursuits:
        job = pursuit.job or {}
        if not _same(str(job.get("company", "")), company, 3):
            continue
        rank = 0
        if requisition and str(job.get("requisition", "")) == requisition:
            rank = 3
        elif _normalize(str(job.get("title", ""))) == _normalize(title):
            rank = 2
        elif _same(str(job.get("title", "")), title, 8):
            rank = 1
        if rank > best_rank:
            best, best_rank = pursuit, rank
    return best


def ensure_review_rule(session: Session) -> None:
    """Seed the application status-check rule once; the user owns it afterwards."""
    if session.scalar(select(FollowUpRule).where(FollowUpRule.rule_key == APPLICATION_REVIEW_RULE)):
        return
    now = datetime.now(UTC)
    session.add(
        FollowUpRule(
            id=uuid4(),
            rule_key=APPLICATION_REVIEW_RULE,
            trigger="application_without_response",
            delay_business_days=5,
            action="create_review_task",
            contact_required_for_outreach=False,
            enabled=True,
            config={"seeded_by": "application_intake"},
            created_at=now,
            updated_at=now,
        )
    )


def _ensure_contact(
    session: Session, message: Communication, company: str, now: datetime
) -> tuple[Contact | None, bool]:
    if message.contact_id:
        return session.get(Contact, message.contact_id), False
    name, address = application_detect.split_sender(message.sender or "")
    if not address:
        return None, False
    existing = session.scalar(
        select(Contact).where(func.lower(func.trim(Contact.email)) == address).limit(1)
    )
    if existing:
        return existing, False
    automated = bool(_AUTOMATED_MAILBOX.search(address))
    surname_first = re.fullmatch(r"\s*([^,]+),\s*([^,]+)\s*", name)
    if surname_first:  # "Lee, Jordan" as some mail systems write it
        name = f"{surname_first.group(2)} {surname_first.group(1)}"
    personal = bool(name.strip()) and "@" not in name and not automated
    # A person writing from another firm's domain is an agency recruiter for this employer.
    from app.correspondence_tasks import _domain_label

    firm = _domain_label(address)
    agency = personal and bool(firm) and not _same(firm, company, 3)
    notes = "Added automatically from an imported email."
    if automated:
        notes += " This looks like an unmonitored mailbox."
    if agency:
        notes += f" Recruiting for {company}."
    contact = Contact(
        id=uuid4(),
        name=(name.strip() if personal else f"{company} Talent Acquisition")[:200],
        company=(firm.upper() if len(firm) <= 3 else firm.capitalize())
        if agency
        else company[:200],
        email=address[:320],
        relationship="recruiter",
        notes=notes,
        do_not_contact=automated,
        created_at=now,
        updated_at=now,
    )
    session.add(contact)
    session.flush()  # no ORM relationship orders this before the message update
    companies.link_contact(session, contact, now)
    return contact, True


def apply_confirmation(
    session: Session,
    message: Communication,
    now: datetime | None = None,
    company: str | None = None,
    title: str | None = None,
    stage: str = "applied",
) -> tuple[Pursuit, bool]:
    """Create, advance or link the application a message refers to. Returns (pursuit, created).

    ``stage`` is where a new application starts: ``applied`` for a confirmation, or
    an earlier stage when the user starts one from a recruiter's message.
    """
    now = now or datetime.now(UTC)
    detected = dict(message.detection or {})
    company = (company or detected.get("company") or "").strip()
    title = (title or detected.get("title") or "").strip()
    if not company or not title:
        raise ValueError("A company and a role are needed to create an application.")
    requisition = str(detected.get("requisition") or "")
    received = message.received_at or now
    prefs = preferences(session)
    follow_up = local_day(prefs, received) + timedelta(days=prefs.follow_up_days)
    pursuit = match_pursuit(
        session.scalars(
            select(Pursuit).where(Pursuit.stage.in_(OPEN_STAGES)).with_for_update()
        ).all(),
        company,
        title,
        requisition,
    )
    applied = {"created_pursuit": False}
    if pursuit is None:
        external_id = message.source_id or str(message.id)
        pursuit_id = session.scalar(
            insert(Pursuit)
            .values(
                id=uuid4(),
                job_key=identity_key(CREATOR, external_id, "", "", ""),
                job={
                    "source": CREATOR,
                    "external_id": external_id,
                    "title": title[:300],
                    "company": company[:200],
                    "location": "",
                    "description": (
                        f"Created from the email “{message.subject}”. Add the posting link"
                        " and details when you have them."
                    ),
                    "url": "",
                    "posted_at": received.isoformat(),
                    "fetched_at": now.isoformat(),
                    "date_kind": "observed",
                    "expired": False,
                    "origins": [],
                    "score": None,
                    "score_breakdown": None,
                    "work_modes": [],
                    "requisition": requisition,
                },
                stage=stage,
                applied_at=received if stage in ("applied", "interview") else None,
                next_action_on=follow_up if stage == "applied" else local_day(prefs, now),
                created_by=CREATOR,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(constraint="pursuit_job_key")
            .returning(Pursuit.id)
        )
        if pursuit_id is None:
            raise ValueError("An application was already created from this message.")
        pursuit = session.get(Pursuit, pursuit_id)
        applied["created_pursuit"] = True
        event = (
            "Application detected from confirmation email"
            if stage == "applied"
            else f"Application created from email at stage: {stage}"
        )
    elif stage == "applied" and pursuit.stage in BEFORE_APPLIED:
        applied.update(
            previous_stage=pursuit.stage,
            previous_next_action_on=(
                pursuit.next_action_on.isoformat() if pursuit.next_action_on else None
            ),
            set_applied_at=pursuit.applied_at is None,
        )
        event = f"Confirmation email recorded stage: {pursuit.stage} → applied"
        pursuit.stage = "applied"
        pursuit.applied_at = pursuit.applied_at or received
        pursuit.next_action_on = follow_up
        if requisition and not pursuit.job.get("requisition"):
            pursuit.job = {**pursuit.job, "requisition": requisition}
        pursuit.version += 1
        pursuit.updated_at = now
    else:
        event = "Application email linked"
    # The wording avoids the sender and subject: follow-up rules read event text for
    # the word "reply", and a "no-reply" address must not look like an answer.
    session.add(
        PursuitEvent(
            id=uuid4(),
            pursuit_id=pursuit.id,
            message=event,
            event_date=received.date(),
            actor=(message.sender or "")[:200],
            source=message.source,
            evidence=f"communication:{message.id}",
            created_at=now,
        )
    )
    companies.link_pursuit(session, pursuit, now)
    contact, created_contact = _ensure_contact(session, message, company, now)
    if contact is not None:
        message.contact_id = contact.id
        applied.update(contact_id=str(contact.id), created_contact=created_contact)
    message.pursuit_id = pursuit.id
    if message.thread_id:
        # The rest of the conversation belongs to the same application.
        siblings = session.scalars(
            select(Communication).where(
                Communication.thread_id == message.thread_id,
                Communication.source == message.source,
                Communication.id != message.id,
                Communication.pursuit_id.is_(None),
                Communication.status != "dismissed",
            )
        ).all()
        for sibling in siblings:
            sibling.pursuit_id = pursuit.id
            sibling.updated_at = now
        if siblings:
            applied["thread_ids"] = [str(sibling.id) for sibling in siblings]
    message.detection = {
        **{key: value for key, value in detected.items() if key != "undone"},
        "kind": detected.get("kind") or application_detect.NONE,
        "company": company,
        "title": title,
        "applied": {
            **applied,
            "pursuit_id": str(pursuit.id),
            "stage": pursuit.stage,
            "at": now.isoformat(),
        },
    }
    message.updated_at = now
    if pursuit.stage == "applied":
        ensure_review_rule(session)
    session.flush()
    return pursuit, applied["created_pursuit"]


def undo_confirmation(session: Session, message: Communication, now: datetime | None = None):
    """Reverse what ``apply_confirmation`` recorded for this message; keeps it from re-running."""
    now = now or datetime.now(UTC)
    detected = dict(message.detection or {})
    applied = detected.pop("applied", None)
    if not applied:
        raise ValueError("No application was recorded from this message.")
    pursuit = session.get(Pursuit, UUID(applied["pursuit_id"]), with_for_update=True)
    if (
        pursuit is not None
        and pursuit.stage != applied.get("stage", "applied")
        and (applied.get("created_pursuit") or applied.get("previous_stage"))
    ):
        raise ValueError(
            f"The application has since moved to {pursuit.stage}; change it from Applications."
        )
    message.pursuit_id = None
    for sibling_id in applied.get("thread_ids", []):
        sibling = session.get(Communication, UUID(sibling_id))
        if sibling is not None and pursuit is not None and sibling.pursuit_id == pursuit.id:
            sibling.pursuit_id = None
            sibling.updated_at = now
    contact_id = applied.get("contact_id") if applied.get("created_contact") else None
    if contact_id:
        message.contact_id = None
    message.detection = {**detected, "undone": True}
    message.updated_at = now
    session.flush()
    if contact_id and not session.scalar(
        select(func.count())
        .select_from(Communication)
        .where(Communication.contact_id == UUID(contact_id))
    ):
        removed = session.get(Contact, UUID(contact_id))
        removed_company = removed.company_id if removed else None
        session.execute(delete(Contact).where(Contact.id == UUID(contact_id)))
        if removed is not None:
            session.expunge(removed)
        companies.refresh_status(session, removed_company)
    if pursuit is None:
        return
    status_check = select(CampaignTask).where(
        CampaignTask.pursuit_id == pursuit.id,
        CampaignTask.seed_key == f"fu-{str(pursuit.id)[:8]}-app",
        CampaignTask.status == "planned",
    )
    if applied.get("created_pursuit"):
        for task in session.scalars(status_check).all():
            session.delete(task)
        session.flush()
        company_id = pursuit.company_id
        session.execute(delete(Pursuit).where(Pursuit.id == pursuit.id))
        session.expunge(pursuit)
        companies.refresh_status(session, company_id)
    elif applied.get("previous_stage"):
        for task in session.scalars(status_check).all():
            session.delete(task)
        pursuit.stage = applied["previous_stage"]
        if applied.get("set_applied_at"):
            pursuit.applied_at = None
        previous = applied.get("previous_next_action_on")
        pursuit.next_action_on = datetime.fromisoformat(previous).date() if previous else None
        pursuit.version += 1
        pursuit.updated_at = now
        companies.link_pursuit(session, pursuit, now)
        session.add(
            PursuitEvent(
                id=uuid4(),
                pursuit_id=pursuit.id,
                message=f"You undid the email-recorded stage: applied → {pursuit.stage}",
                created_at=now,
            )
        )
    else:
        session.add(
            PursuitEvent(
                id=uuid4(),
                pursuit_id=pursuit.id,
                message="You unlinked an application email",
                created_at=now,
            )
        )


def run(session: Session, now: datetime | None = None) -> dict:
    """Apply every unhandled high-confidence confirmation when the user opted in."""
    config = session.get(CorrespondenceSyncSettings, 1)
    if config is None or not config.auto_create_applications:
        return {"status": "disabled", "created": 0, "advanced": 0, "linked": 0}
    candidates = session.scalars(
        select(Communication)
        .where(
            Communication.direction == "inbound",
            Communication.status == "received",
            Communication.pursuit_id.is_(None),
            Communication.detection["kind"].astext == application_detect.CONFIRMATION,
            Communication.detection["confidence"].astext == "high",
        )
        .order_by(Communication.received_at)
        .with_for_update()
    ).all()
    counts = {"created": 0, "advanced": 0, "linked": 0}
    # A confirmation applied before its sender could be read still gets its contact.
    for message in session.scalars(
        select(Communication)
        .where(
            Communication.pursuit_id.is_not(None),
            Communication.contact_id.is_(None),
            Communication.detection["applied"]["pursuit_id"].astext.is_not(None),
        )
        .with_for_update()
    ).all():
        contact, created = _ensure_contact(
            session, message, message.detection.get("company", ""), now or datetime.now(UTC)
        )
        if contact is not None:
            message.contact_id = contact.id
            message.detection = {
                **message.detection,
                "applied": {
                    **message.detection["applied"],
                    "contact_id": str(contact.id),
                    "created_contact": created,
                },
            }
    for message in candidates:
        if message.detection.get("undone") or message.detection.get("applied"):
            continue
        try:
            _, created = apply_confirmation(session, message, now)
        except ValueError:
            continue
        outcome = message.detection["applied"]
        counts[
            "created" if created else "advanced" if outcome.get("previous_stage") else "linked"
        ] += 1
    return {"status": "ok", **counts}


class ApplicationFromMail(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    company: str | None = Field(default=None, min_length=1, max_length=200, pattern=r"^[^\x00]+$")
    title: str | None = Field(default=None, min_length=1, max_length=300, pattern=r"^[^\x00]+$")
    # Where a new application starts; a recruiter's first message is not yet "applied".
    stage: Literal["review", "preparing", "applied", "interview"] = "applied"


def _locked_message(session: Session, comm_id: UUID) -> Communication:
    message = session.get(Communication, comm_id, with_for_update=True)
    if message is None:
        raise HTTPException(404, "Communication not found")
    return message


@router.post("/api/communications/{comm_id}/application", status_code=201)
def create_application(comm_id: UUID, body: ApplicationFromMail, session: Database):
    """Create or advance an application from one imported message, on the user's request."""
    message = _locked_message(session, comm_id)
    if message.direction != "inbound" or message.status == "dismissed":
        raise HTTPException(409, "Only received mail can create an application.")
    if message.pursuit_id is not None:
        raise HTTPException(409, "This message is already linked to an application.")
    try:
        pursuit, created = apply_confirmation(
            session, message, company=body.company, title=body.title, stage=body.stage
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    session.commit()
    return {
        "pursuit_id": pursuit.id,
        "created": created,
        "stage": pursuit.stage,
        "company": pursuit.job.get("company", ""),
        "title": pursuit.job.get("title", ""),
        "contact_id": message.contact_id,
    }


@router.delete("/api/communications/{comm_id}/application", status_code=204)
def undo_application(comm_id: UUID, session: Database):
    message = _locked_message(session, comm_id)
    try:
        undo_confirmation(session, message)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    session.commit()


# ---------- Stage suggestions: rejections and interview invitations ----------

CLOSED_STAGES = ("accepted", "rejected", "withdrawn", "dismissed")
BEFORE_INTERVIEW = ("review", "preparing", "applied")


def _suggestion_target(message: Communication, pursuits: dict[UUID, Pursuit]) -> Pursuit | None:
    """The application a message is about: its link, the sync's suggestion, or the employer."""
    for pursuit_id in (message.pursuit_id, message.suggested_pursuit_id):
        if pursuit_id and pursuit_id in pursuits:
            return pursuits[pursuit_id]
    detected = message.detection or {}
    company = str(detected.get("company") or "")
    if not company:
        return None
    candidates = [p for p in pursuits.values() if p.stage not in CLOSED_STAGES]
    named = match_pursuit(
        candidates,
        company,
        str(detected.get("title") or ""),
        str(detected.get("requisition") or ""),
    )
    if named is not None:
        return named
    same_employer = [p for p in candidates if _same(str(p.job.get("company", "")), company, 3)]
    return same_employer[0] if len(same_employer) == 1 else None


def stage_suggestion(message: Communication, pursuits: dict[UUID, Pursuit]) -> dict | None:
    """What a rejection or interview message proposes, if it would change a stage."""
    detected = message.detection or {}
    stage = application_detect.STAGE_FOR_KIND.get(detected.get("kind"))
    if stage is None or detected.get("stage_decision") or message.status == "dismissed":
        return None
    pursuit = _suggestion_target(message, pursuits)
    if pursuit is None:
        return None
    if stage == "interview" and pursuit.stage not in BEFORE_INTERVIEW:
        return None
    if stage == "rejected" and pursuit.stage in CLOSED_STAGES:
        return None
    return {
        "stage": stage,
        "pursuit_id": pursuit.id,
        "current_stage": pursuit.stage,
        "company": pursuit.job.get("company", ""),
        "title": pursuit.job.get("title", ""),
        "evidence": detected.get("evidence", ""),
    }


@router.get("/api/stage-suggestions")
def list_stage_suggestions(session: Database):
    """Imported messages that suggest moving an application to rejected or interview."""
    from app.contacts import _comm_out

    messages = session.scalars(
        select(Communication)
        .where(
            Communication.detection["kind"].astext.in_(list(application_detect.STAGE_FOR_KIND)),
            Communication.status != "dismissed",
        )
        .order_by(func.coalesce(Communication.received_at, Communication.created_at).desc())
        .limit(500)
    ).all()
    if not messages:
        return []
    pursuits = {p.id: p for p in session.scalars(select(Pursuit)).all()}
    found, seen = [], set()
    for message in messages:
        suggestion = stage_suggestion(message, pursuits)
        # One open suggestion per application and stage: the newest message speaks for it.
        if suggestion and (suggestion["pursuit_id"], suggestion["stage"]) not in seen:
            seen.add((suggestion["pursuit_id"], suggestion["stage"]))
            found.append({**suggestion, "communication": _comm_out(message)})
    return found


class StageDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decision: Literal["apply", "ignore"]


@router.post("/api/communications/{comm_id}/stage-suggestion")
def decide_stage_suggestion(comm_id: UUID, body: StageDecision, session: Database):
    """Confirm or ignore one suggestion. Confirming moves the stage and links the message."""
    message = _locked_message(session, comm_id)
    pursuits = {p.id: p for p in session.scalars(select(Pursuit).with_for_update()).all()}
    suggestion = stage_suggestion(message, pursuits)
    if suggestion is None:
        raise HTTPException(409, "This message no longer suggests a stage change.")
    now = datetime.now(UTC)
    pursuit = pursuits[suggestion["pursuit_id"]]
    stage, before = suggestion["stage"], pursuit.stage
    decision = {"decision": "ignored", "stage": stage, "at": now.isoformat()}
    if body.decision == "apply":
        prefs = preferences(session)
        today = local_day(prefs, now)
        pursuit.stage = stage
        pursuit.next_action_on = today if stage == "interview" else None
        pursuit.version += 1
        pursuit.updated_at = now
        happened = message.received_at or now
        session.add(
            PursuitEvent(
                id=uuid4(),
                pursuit_id=pursuit.id,
                message=f"Email recorded stage: {before} → {stage}",
                event_date=happened.date() if message.source == "gmail" else today,
                actor=(message.sender or "")[:200],
                source=message.source,
                evidence=f"communication:{message.id}",
                created_at=now,
            )
        )
        message.pursuit_id = pursuit.id
        decision = {
            "decision": "applied",
            "stage": stage,
            "previous_stage": before,
            "pursuit_id": str(pursuit.id),
            "at": now.isoformat(),
        }
        if stage == "interview":
            # A calendar event knows when the interview is; mail only says one is coming.
            when = happened.date() if message.source == "calendar" else today
            _ensure_prep_task(session, pursuit, message, max(today, when - timedelta(days=1)), now)
    message.detection = {**(message.detection or {}), "stage_decision": decision}
    message.updated_at = now
    session.commit()
    return {**decision, "pursuit_id": pursuit.id, "current_stage": pursuit.stage}


def _ensure_prep_task(session, pursuit: Pursuit, message: Communication, due, now) -> None:
    campaign = session.scalar(select(Campaign).where(Campaign.is_active).limit(1))
    if campaign is None:
        return
    seed_key = f"fu-{str(pursuit.id)[:8]}-prep"
    if session.scalar(
        select(CampaignTask).where(
            CampaignTask.campaign_id == campaign.id, CampaignTask.seed_key == seed_key
        )
    ):
        return
    company, title = pursuit.job.get("company", ""), pursuit.job.get("title", "")
    session.add(
        CampaignTask(
            id=uuid4(),
            campaign_id=campaign.id,
            seed_key=seed_key,
            title=f"Prepare for interview: {title} at {company}"[:500],
            category="interview",
            status="planned",
            priority="P0",
            due_date=due,
            estimated_minutes=60,
            pursuit_id=pursuit.id,
            communication_id=message.id,
            completion_criteria=(
                "Confirm the time and format, research the interviewers, and prepare examples"
                " and questions. The message that prompted this is attached."
            ),
            created_at=now,
            updated_at=now,
        )
    )
