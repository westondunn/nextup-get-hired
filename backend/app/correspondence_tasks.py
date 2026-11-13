"""Read-only Gmail correspondence sync. Runs on the existing Beat scheduler.

Imports matching messages as ``communications`` rows (the user's own sent mail as
outbound), links exact contact email matches, classifies each message locally, and
*suggests* a pursuit. With the opt-in setting, a recognized application confirmation
then creates or advances the application (see ``application_intake``). It never sends
mail and never changes labels.
"""

import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from sqlalchemy import Integer, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import application_detect, email_classifications
from app.celery_app import celery_app
from app.config import Settings, get_settings
from app.db import get_engine
from app.models import Communication, Contact, CorrespondenceSyncSettings, Pursuit
from app.sources import gmail, google_calendar
from app.sources.common import SourceError

SOURCE = "gmail"
CALENDAR_SOURCE = "calendar"
INTERVIEW_HINT = (
    "Imported from Google Calendar. If this is an interview, link it to the pursuit and"
    " move the stage to interview yourself; nothing changes automatically."
)
INITIAL_LOOKBACK_DAYS = 30
MAX_LISTED_IDS = 500
OPEN_STAGES = ("review", "preparing", "applied", "interview", "offer")
GENERIC_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "yahoo.com",
        "icloud.com",
        "me.com",
        "proton.me",
        "protonmail.com",
        "greenhouse.io",
        "greenhouse-mail.io",
        "lever.co",
        "hire.lever.co",
        "ashbyhq.com",
        "workday.com",
        "myworkday.com",
        "linkedin.com",
        "indeed.com",
        "icims.com",
        "myworkdayjobs.com",
        "smartrecruiters.com",
        "jobvite.com",
        "taleo.net",
        "successfactors.com",
        "workablemail.com",
        "bamboohr.com",
    }
)


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


# Words too common in employer names to identify one on their own.
COMMON_COMPANY_WORDS = frozenset(
    """american bank capital company consulting corporation digital engineering enterprise
    enterprises financial global group health healthcare holdings incorporated industries
    insurance international interactive limited management media national network networks
    partners services software solutions staffing systems technologies technology united
    ventures""".split()
)
BODY_MATCH_CHARS = 3000


def _generic(domain: str) -> bool:
    return any(domain == known or domain.endswith("." + known) for known in GENERIC_DOMAINS)


RESERVED_TLDS = frozenset({"example", "test", "invalid"})


def _domain_label(email: str) -> str:
    domain = email.rsplit("@", 1)[-1].casefold() if "@" in email else ""
    if not domain or _generic(domain):
        return ""
    labels = [label for label in domain.split(".") if label]
    # A reserved top-level domain (RFC 2606) is a suffix too: acme.example -> acme.
    if len(labels) > 1 and labels[-1] in RESERVED_TLDS:
        labels.pop()
    # Drop the public suffix and any country code: mail.acme.co.uk -> acme.
    while len(labels) > 1 and len(labels[-1]) <= 3:
        labels.pop()
    return _normalize(labels[-1]) if labels else ""


def _distinctive_words(company: str) -> set[str]:
    """Words that can stand for the employer alone: "Northwind" for "Harlow Northwind"."""
    return {
        word
        for word in re.findall(r"[a-z0-9]+", company.casefold())
        if len(word) >= 5 and word not in COMMON_COMPANY_WORDS
    }


def suggest_pursuit(message: gmail.ParsedMessage, pursuits: list[Pursuit]) -> Pursuit | None:
    """Suggest the open pursuit whose company the message points to.

    Strongest first: the sender's own domain; the full company name in the subject or
    sender name (how applicant-tracking mailers and "[Client]" recruiter subjects name
    it); one distinctive word of the name there; the full name early in the body. A
    tie at the weaker ranks is ambiguous and suggests nothing.
    """
    label = _domain_label(message.sender_email)
    heading = f"{message.subject} {message.sender_name}"
    haystack = _normalize(heading)
    heading_words = set(re.findall(r"[a-z0-9]+", heading.casefold()))
    body = _normalize(message.body[:BODY_MATCH_CHARS])
    ranked: dict[int, list[Pursuit]] = {}
    for pursuit in pursuits:
        name = str(pursuit.job.get("company", ""))
        company = _normalize(name)
        if len(company) < 3:
            continue
        if label and (company == label or label in company or company in label):
            rank = 4
        elif company in haystack:
            rank = 3
        elif _distinctive_words(name) & heading_words:
            rank = 2
        elif len(company) >= 5 and company in body:
            rank = 1
        else:
            continue
        ranked.setdefault(rank, []).append(pursuit)
    if not ranked:
        return None
    top = max(ranked)
    candidates = ranked[top]
    # Several applications at one employer are common; any of them is a useful default
    # when the evidence is strong. Weak evidence naming two employers suggests nothing.
    if top <= 2 and len({_normalize(str(p.job.get("company", ""))) for p in candidates}) > 1:
        return None
    return candidates[0]


def _record_result(config: CorrespondenceSyncSettings, status: str, error: str, imported: int):
    config.last_run_at = datetime.now(UTC)
    config.last_status = status
    config.last_error = error[:1000]
    config.last_imported = imported
    config.updated_at = datetime.now(UTC)


def _classify_stored(session: Session, client: httpx.Client, token: str) -> int:
    """Classify stored mail the current rules have not seen; once per message and version.

    Covers mail imported before detection existed and, after a rules change, mail the
    older rules found nothing in. Decisions already recorded on a message are kept.
    Earlier versions also stored the user's own sent messages as inbound; those are
    recognized by the mailbox address and corrected to sent outbound mail.
    """
    stored = session.scalars(
        select(Communication).where(
            Communication.source == SOURCE,
            or_(
                Communication.detection.is_(None),
                func.coalesce(Communication.detection["v"].astext.cast(Integer), 1)
                < application_detect.VERSION,
            ),
        )
    ).all()
    if not stored:
        return 0
    nothing = application_detect.Detection().as_dict()
    own = gmail.profile_email(client, token) if any(r.detection is None for r in stored) else ""
    for row in stored:
        name, address = application_detect.split_sender(row.sender or "")
        previous = row.detection
        if previous is not None and (
            previous.get("kind") != application_detect.NONE
            or previous.get("applied")
            or previous.get("undone")
        ):
            row.detection = {**previous, "v": application_detect.VERSION}
        elif row.direction != "inbound":
            row.detection = nothing
        elif previous is None and own and address == own:
            row.direction, row.status = "outbound", "sent"
            row.sent_at = row.sent_at or row.received_at
            row.detection = nothing
        else:
            row.detection = application_detect.classify(
                row.subject, row.body, name, address
            ).as_dict()
        hint = (previous or {}).get(email_classifications.HINT_KEY)
        if hint and email_classifications.HINT_KEY not in row.detection:
            # The external classifier's hint outlives a re-run of Nextup's own rules.
            kind = row.detection.get("kind")
            hint = {**hint, "agrees": email_classifications.agrees(kind, hint["classification"])}
            row.detection = {**row.detection, email_classifications.HINT_KEY: hint}
    return len(stored)


def _interview_event(subject: str, description: str) -> dict:
    """Calendar events are only ever classified as an interview or as nothing."""
    found = application_detect.classify(subject, description)
    if found.kind != application_detect.INTERVIEW:
        found = application_detect.Detection()
    return found.as_dict()


def sync_gmail(
    session: Session,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> dict:
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    config = session.get(CorrespondenceSyncSettings, 1, with_for_update=True)
    if config is None or not config.enabled:
        return {"status": "disabled", "imported": 0}
    if not settings.gmail_sync_enabled or not gmail.credentials_present(settings):
        _record_result(config, "not_configured", "Gmail credentials are not configured.", 0)
        return {"status": "not_configured", "imported": 0}
    if client is None:
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as owned:
            return sync_gmail(session, settings, client=owned, now=now)

    imported = 0
    try:
        token = gmail.refresh_access_token(client, settings)
        lookback = now - timedelta(days=INITIAL_LOOKBACK_DAYS)
        after = config.cursor_epoch or int(lookback.timestamp())
        query = f"{config.query.strip()} after:{after}".strip()
        refs = gmail.list_message_refs(client, token, query, MAX_LISTED_IDS)
        ids = [message_id for message_id, _ in refs]
        known = set(
            session.scalars(
                select(Communication.source_id).where(
                    Communication.source == SOURCE, Communication.source_id.in_(ids or [""])
                )
            ).all()
        )
        pending = [message_id for message_id in ids if message_id not in known]
        batch = pending[: config.max_messages_per_run]
        contacts = {
            c.email.strip().lower(): c
            for c in session.scalars(select(Contact).where(Contact.email.is_not(None))).all()
            if c.email and c.email.strip()
        }
        pursuits = session.scalars(select(Pursuit).where(Pursuit.stage.in_(OPEN_STAGES))).all()
        newest = config.cursor_epoch or 0
        try:
            _classify_stored(session, client, token)
        except SourceError:
            pass  # Unclassified rows stay NULL and are retried on the next run.
        for message_id in batch:
            message = gmail.parse_message(gmail.fetch_message(client, token, message_id))
            # Mail the user sent is logged as sent, so it is never treated as awaiting a reply.
            own = message.is_sent
            contact = contacts.get(message.recipient_email if own else message.sender_email)
            # For your own mail the employer is on the receiving end.
            suggestion = suggest_pursuit(
                replace(message, sender_email=message.recipient_email, sender_name="")
                if own
                else message,
                pursuits,
            )
            detection = (
                application_detect.Detection()
                if own
                else application_detect.classify(
                    message.subject,
                    message.body,
                    message.sender_name,
                    message.sender_email,
                    message.auto_reply,
                )
            )
            session.add(
                Communication(
                    id=uuid4(),
                    contact_id=contact.id if contact else None,
                    pursuit_id=None,
                    campaign_task_id=None,
                    channel="email",
                    direction="outbound" if own else "inbound",
                    subject=message.subject,
                    body=message.body,
                    status="sent" if own else "received",
                    sent_at=message.received_at if own else None,
                    received_at=message.received_at,
                    notes="",
                    source=SOURCE,
                    source_id=message.source_id,
                    thread_id=message.thread_id or None,
                    sender=(
                        f"{message.sender_name} <{message.sender_email}>"
                        if message.sender_name
                        else message.sender_email
                    )[:320]
                    or None,
                    suggested_pursuit_id=suggestion.id if suggestion else None,
                    detection=detection.as_dict(),
                    created_at=now,
                    updated_at=now,
                )
            )
            imported += 1
            newest = max(newest, int(message.received_at.timestamp()))
        if len(pending) <= len(batch) and newest:
            # Every listed message is stored; later runs only need newer mail.
            config.cursor_epoch = newest
        # The external classifier's verdicts, whether written before these imports or since.
        session.flush()
        classified = email_classifications.reconcile(session, now)
        _record_result(config, "ok", "", imported)
        return {
            "status": "ok",
            "imported": imported,
            "remaining": len(pending) - len(batch),
            "classifications": classified,
        }
    except SourceError as exc:
        _record_result(config, exc.code, exc.message, imported)
        return {"status": exc.code, "imported": imported, "error": exc.message}


@celery_app.task(bind=True, name="app.correspondence_tasks.sync_gmail")
def sync_gmail_task(self):
    try:
        from app import application_intake

        with Session(get_engine()) as session, session.begin():
            result = sync_gmail(session)
            session.flush()
            return {**result, "applications": application_intake.run(session)}
    except SQLAlchemyError:
        raise self.retry(
            exc=RuntimeError("Correspondence sync unavailable"), countdown=30, max_retries=2
        ) from None


def _calendar_result(config: CorrespondenceSyncSettings, status: str, error: str, imported: int):
    config.calendar_last_run_at = datetime.now(UTC)
    config.calendar_last_status = status
    config.calendar_last_error = error[:1000]
    config.calendar_last_imported = imported
    config.updated_at = datetime.now(UTC)


def _event_body(event: google_calendar.ParsedEvent) -> str:
    when = "all day" if event.all_day else event.starts_at.isoformat()
    if event.ends_at and not event.all_day:
        when += f" to {event.ends_at.isoformat()}"
    people = ", ".join(
        f"{name} <{email}>" if name else email
        for name, email in zip(event.attendee_names, event.attendee_emails, strict=True)
    )
    lines = [f"When: {when}"]
    if event.location:
        lines.append(f"Where: {event.location}")
    if event.link:
        lines.append(f"Link: {event.link}")
    if people:
        lines.append(f"With: {people}")
    if event.description:
        lines.append("")
        lines.append(event.description)
    return "\n".join(lines)[: google_calendar.MAX_BODY_CHARS + 2000]


def sync_calendar(
    session: Session,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> dict:
    """Log upcoming and just-finished events as review-queue notes. Read-only."""
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    config = session.get(CorrespondenceSyncSettings, 1, with_for_update=True)
    if config is None or not config.calendar_enabled:
        return {"status": "disabled", "imported": 0}
    if not settings.calendar_sync_enabled or not gmail.credentials_present(settings):
        _calendar_result(config, "not_configured", "Google credentials are not configured.", 0)
        return {"status": "not_configured", "imported": 0}
    if client is None:
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as owned:
            return sync_calendar(session, settings, client=owned, now=now)

    imported = updated = 0
    try:
        token = google_calendar.refresh_access_token(client, settings)
        start, end = google_calendar.window(now, config.calendar_lookahead_days)
        events = [
            parsed
            for parsed in map(
                google_calendar.parse_event, google_calendar.list_events(client, token, start, end)
            )
            if parsed is not None
        ]
        ids = [event.source_id for event in events]
        existing = {
            row.source_id: row
            for row in session.scalars(
                select(Communication).where(
                    Communication.source == CALENDAR_SOURCE,
                    Communication.source_id.in_(ids or [""]),
                )
            ).all()
        }
        contacts = {
            c.email.strip().lower(): c
            for c in session.scalars(select(Contact).where(Contact.email.is_not(None))).all()
            if c.email and c.email.strip()
        }
        pursuits = session.scalars(select(Pursuit).where(Pursuit.stage.in_(OPEN_STAGES))).all()
        for event in events:
            subject = event.summary or "(untitled event)"
            body = _event_body(event)
            row = existing.get(event.source_id)
            if row is not None:
                if row.detection is None:
                    row.detection = _interview_event(subject, event.description)
                if row.subject != subject or row.body != body or row.received_at != event.starts_at:
                    row.subject, row.body, row.received_at = subject, body, event.starts_at
                    row.updated_at = now
                    updated += 1
                continue
            people = list(event.attendee_emails)
            if event.organizer_email:
                people.append(event.organizer_email)
            contact = next((contacts[email] for email in people if email in contacts), None)
            counterpart = next((email for email in people if email not in contacts), "")
            message = gmail.ParsedMessage(
                source_id=event.source_id,
                thread_id="",
                sender_name=event.organizer_name,
                sender_email=counterpart or event.organizer_email,
                subject=f"{subject} {event.description[:500]}",
                body="",
                received_at=event.starts_at,
            )
            suggestion = suggest_pursuit(message, pursuits)
            virtual = bool(event.link) or not event.location or "://" in event.location
            session.add(
                Communication(
                    id=uuid4(),
                    contact_id=contact.id if contact else None,
                    pursuit_id=None,
                    campaign_task_id=None,
                    channel="other" if virtual else "in_person",
                    direction="note",
                    subject=subject,
                    body=body,
                    status="private_note",
                    received_at=event.starts_at,
                    notes=INTERVIEW_HINT,
                    source=CALENDAR_SOURCE,
                    source_id=event.source_id,
                    thread_id=None,
                    detection=_interview_event(subject, event.description),
                    sender=(
                        f"{event.organizer_name} <{event.organizer_email}>"
                        if event.organizer_name
                        else event.organizer_email
                    )[:320]
                    or None,
                    suggested_pursuit_id=suggestion.id if suggestion else None,
                    created_at=now,
                    updated_at=now,
                )
            )
            imported += 1
        _calendar_result(config, "ok", "", imported)
        return {"status": "ok", "imported": imported, "updated": updated}
    except SourceError as exc:
        _calendar_result(config, exc.code, exc.message, imported)
        return {"status": exc.code, "imported": imported, "error": exc.message}


@celery_app.task(bind=True, name="app.correspondence_tasks.sync_calendar")
def sync_calendar_task(self):
    try:
        with Session(get_engine()) as session, session.begin():
            return sync_calendar(session)
    except SQLAlchemyError:
        raise self.retry(
            exc=RuntimeError("Calendar sync unavailable"), countdown=30, max_retries=2
        ) from None


def review_count(session: Session) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Communication)
            .where(
                Communication.source != "manual",
                Communication.status != "dismissed",
                Communication.contact_id.is_(None),
                Communication.pursuit_id.is_(None),
            )
        )
        or 0
    )
