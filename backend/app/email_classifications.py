"""Apply an external classifier's verdicts to imported Gmail messages, as hints.

The classifier upserts ``email_classifications`` (one row per Gmail message id); it never
writes ``communications``. After each Gmail sync run, ``reconcile`` merges every
unapplied classification whose message has been imported into
``communications.detection[HINT_KEY]`` and stamps ``applied_at``. Because it runs after
the run's imports are flushed, a classification written before the import is applied
in the same run, one written later is applied on the next run, and a
re-classification (the upsert clears ``applied_at``) replaces the earlier hint.

Nextup's own detection stays authoritative: ``kind`` and every other key, ``status``,
and the actual pursuit and contact links are never changed. Only an empty
``suggested_pursuit_id`` may be filled from the matched company, and disagreements
are recorded in ``detection[HINT_KEY]['agrees']`` for prompt tuning.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import application_detect
from app.models import Communication, Company, EmailClassification, Pursuit

SOURCE = "gmail"
# Key of the hint inside ``communications.detection``. It is stored data, and the downgrade
# of pinned migration 0029 removes it by this name, so it must never change. The API
# returns the hint under the neutral key ``classifier`` instead.
HINT_KEY = "n8n"
CLOSED_STAGES = ("accepted", "rejected", "withdrawn", "dismissed")
# What Nextup's own detection implies the labeler should have said. Kinds missing
# here (none, auto_reply) carry no opinion, so they never count as a disagreement.
EXPECTED = {
    application_detect.CONFIRMATION: "new_application",
    application_detect.REJECTION: "new_application",
    application_detect.INTERVIEW: "opportunity",
}


def agrees(nextup_kind: str | None, classification: str) -> bool | None:
    expected = EXPECTED.get(nextup_kind or "")
    return None if expected is None else classification == expected


def _suggested_pursuit(session: Session, company_id) -> Pursuit | None:
    return session.scalar(
        select(Pursuit)
        .where(Pursuit.company_id == company_id, Pursuit.stage.not_in(CLOSED_STAGES))
        .order_by(Pursuit.updated_at.desc(), Pursuit.id)
        .limit(1)
    )


def apply(session: Session, message: Communication, row: EmailClassification, now: datetime):
    """Merge one classification into the message; returns (suggested, disagreed)."""
    detection = dict(message.detection or {})
    company = session.get(Company, row.company_id) if row.company_id else None
    verdict = agrees(detection.get("kind"), row.classification)
    detection[HINT_KEY] = {
        "classification": row.classification,
        "companies": list(row.companies or []),
        "company_id": str(row.company_id) if row.company_id else None,
        "company_name": company.name if company else None,
        "confidence": float(row.confidence) if row.confidence is not None else None,
        "model": row.model,
        "prompt_version": row.prompt_version,
        "classified_at": row.classified_at.isoformat() if row.classified_at else None,
        "agrees": verdict,
    }
    message.detection = detection
    suggested = False
    if message.suggested_pursuit_id is None and row.company_id is not None:
        pursuit = _suggested_pursuit(session, row.company_id)
        if pursuit is not None:
            message.suggested_pursuit_id = pursuit.id
            suggested = True
    message.updated_at = now
    return suggested, verdict is False


def reconcile(session: Session, now: datetime | None = None) -> dict:
    """Apply every unapplied classification whose Gmail message has been imported."""
    now = now or datetime.now(UTC)
    pairs = session.execute(
        select(EmailClassification, Communication)
        .join(
            Communication,
            (Communication.source == SOURCE)
            & (Communication.source_id == EmailClassification.gmail_message_id),
        )
        .where(EmailClassification.applied_at.is_(None))
        .order_by(EmailClassification.classified_at)
        .with_for_update(of=EmailClassification, skip_locked=True)
    ).all()
    counts = {"applied": 0, "suggested": 0, "disagreements": 0}
    for row, message in pairs:
        suggested, disagreed = apply(session, message, row, now)
        row.applied_at = now
        counts["applied"] += 1
        counts["suggested"] += int(suggested)
        counts["disagreements"] += int(disagreed)
    return counts
