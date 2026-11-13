"""Evaluate follow-up rules and create campaign tasks. Runs every 5 minutes.

Only creates internal tasks — never sends anything. Uses idempotent keys
to prevent duplicates across replays, retries, and restarts.
"""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.application_detect import NO_ANSWER_NEEDED
from app.celery_app import celery_app
from app.db import get_engine
from app.models import Campaign, CampaignTask, Communication, FollowUpRule, Pursuit, PursuitEvent

CLOSED_STAGES = ("accepted", "rejected", "withdrawn", "dismissed")
INBOUND_REPLY_RULE = "inbound_reply"


def _add_business_days(start: date, days: int) -> date:
    """Add business days (Mon-Fri) to a date."""
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Mon=0, Fri=4
            added += 1
    return current


def _evaluate_rules(session: Session):
    rules = session.scalars(select(FollowUpRule).where(FollowUpRule.enabled)).all()
    if not rules:
        return {"evaluated": 0, "created": 0}

    campaign = session.scalar(select(Campaign).where(Campaign.is_active).limit(1))
    if not campaign:
        return {"evaluated": 0, "created": 0, "reason": "no_active_campaign"}

    today = datetime.now(UTC).date()
    rule_map = {r.rule_key: r for r in rules}
    pursuits = session.scalars(select(Pursuit)).all()
    created = 0

    for p in pursuits:
        # Skip closed pursuits
        if p.stage in ("accepted", "rejected", "withdrawn", "dismissed"):
            continue

        pid = str(p.id)
        company = p.job.get("company", "")
        title = p.job.get("title", "")

        # Get pursuit events
        events = session.scalars(
            select(PursuitEvent)
            .where(PursuitEvent.pursuit_id == p.id)
            .order_by(PursuitEvent.created_at.desc())
        ).all()

        # A reply, or contact you recorded yourself since applying, makes a status
        # check redundant ("You recorded contact: ..." is how the event is worded).
        has_reply = any(
            "reply" in e.message.lower()
            or "responded" in e.message.lower()
            or "recorded contact" in e.message.lower()
            for e in events
            if e.created_at and e.created_at > (p.applied_at or datetime.min.replace(tzinfo=UTC))
        )

        # Rule: application_review — 5 business days after confirmed application
        rule = rule_map.get("application_review")
        if rule and p.applied_at and not has_reply:
            due = _add_business_days(p.applied_at.date(), rule.delay_business_days)
            if due <= today:
                seed_key = f"fu-{pid[:8]}-app"
                existing = session.scalar(
                    select(CampaignTask).where(
                        CampaignTask.campaign_id == campaign.id,
                        CampaignTask.seed_key == seed_key,
                    )
                )
                if not existing:
                    session.add(
                        CampaignTask(
                            id=uuid4(),
                            campaign_id=campaign.id,
                            seed_key=seed_key,
                            title=f"Review application status: {title} at {company}",
                            category="follow_up",
                            status="planned",
                            priority="P1",
                            due_date=due,
                            estimated_minutes=15,
                            pursuit_id=p.id,
                            completion_criteria=(
                                f"Check for response from {company}."
                                " If no reply and appropriate contact exists, consider outreach."
                            ),
                            created_at=datetime.now(UTC),
                            updated_at=datetime.now(UTC),
                        )
                    )
                    created += 1

        # Rule: interview_thank_you — 1 business day after interview stage
        rule = rule_map.get("interview_thank_you")
        if rule and p.stage == "interview":
            interview_event = next((e for e in events if "→ interview" in e.message), None)
            if interview_event and interview_event.created_at:
                due = _add_business_days(
                    interview_event.created_at.date(), rule.delay_business_days
                )
                seed_key = f"fu-{pid[:8]}-thx"
                existing = session.scalar(
                    select(CampaignTask).where(
                        CampaignTask.campaign_id == campaign.id,
                        CampaignTask.seed_key == seed_key,
                    )
                )
                if not existing:
                    session.add(
                        CampaignTask(
                            id=uuid4(),
                            campaign_id=campaign.id,
                            seed_key=seed_key,
                            title=f"Send thank-you/follow-up: {title} at {company}",
                            category="follow_up",
                            status="planned",
                            priority="P0",
                            due_date=due,
                            estimated_minutes=15,
                            pursuit_id=p.id,
                            completion_criteria=(
                                f"Send a thank-you or promised material to {company} interviewer."
                                " Record as sent only when actually delivered."
                            ),
                            created_at=datetime.now(UTC),
                            updated_at=datetime.now(UTC),
                        )
                    )
                    created += 1

        # Rule: interview_status_review — 5 business days after interview with no promised date
        rule = rule_map.get("interview_status_review")
        if rule and p.stage == "interview" and not has_reply:
            interview_event = next((e for e in events if "→ interview" in e.message), None)
            if interview_event and interview_event.created_at:
                due = _add_business_days(
                    interview_event.created_at.date(), rule.delay_business_days
                )
                if due <= today:
                    seed_key = f"fu-{pid[:8]}-isr"
                    existing = session.scalar(
                        select(CampaignTask).where(
                            CampaignTask.campaign_id == campaign.id,
                            CampaignTask.seed_key == seed_key,
                        )
                    )
                    if not existing:
                        session.add(
                            CampaignTask(
                                id=uuid4(),
                                campaign_id=campaign.id,
                                seed_key=seed_key,
                                title=f"Check interview status: {title} at {company}",
                                category="follow_up",
                                status="planned",
                                priority="P1",
                                due_date=due,
                                estimated_minutes=10,
                                pursuit_id=p.id,
                                completion_criteria=(
                                    f"No response after {rule.delay_business_days} business days."
                                    " Check status if no promised timeline exists."
                                ),
                                created_at=datetime.now(UTC),
                                updated_at=datetime.now(UTC),
                            )
                        )
                        created += 1

    created += _evaluate_inbound_replies(session, campaign, rule_map.get(INBOUND_REPLY_RULE), today)
    return {"evaluated": len(pursuits), "created": created}


def _evaluate_inbound_replies(session: Session, campaign: Campaign, rule, today: date) -> int:
    """Create one review task per linked inbound message that has waited too long for a reply.

    Only messages linked to a contact or pursuit count; the review queue is the user's.
    A sent outbound message to the same contact or pursuit after the inbound one, or a
    closed pursuit, suppresses the task. Nothing is sent and no stage changes.
    """
    if rule is None:
        return 0
    inbound = session.scalars(
        select(Communication).where(
            Communication.direction == "inbound",
            Communication.status == "received",
            Communication.received_at.is_not(None),
            (Communication.contact_id.is_not(None)) | (Communication.pursuit_id.is_not(None)),
        )
    ).all()
    # Confirmations, automatic replies and rejections are not waiting for an answer.
    inbound = [m for m in inbound if (m.detection or {}).get("kind") not in NO_ANSWER_NEEDED]
    if not inbound:
        return 0
    outbound = session.scalars(
        select(Communication).where(
            Communication.direction == "outbound",
            Communication.status == "sent",
            Communication.sent_at.is_not(None),
        )
    ).all()
    stages = {
        p.id: p.stage
        for p in session.scalars(
            select(Pursuit).where(Pursuit.id.in_({c.pursuit_id for c in inbound if c.pursuit_id}))
        ).all()
    }
    # One task per thread: only the newest linked message of a Gmail thread is due.
    newest_in_thread: dict[str, Communication] = {}
    for message in inbound:
        if message.thread_id:
            current = newest_in_thread.get(message.thread_id)
            if current is None or message.received_at > current.received_at:
                newest_in_thread[message.thread_id] = message
    created = 0
    for message in inbound:
        if message.thread_id and newest_in_thread[message.thread_id] is not message:
            continue
        if message.pursuit_id and stages.get(message.pursuit_id) in CLOSED_STAGES:
            continue
        replied = any(
            reply.sent_at >= message.received_at
            and (
                (message.pursuit_id and reply.pursuit_id == message.pursuit_id)
                or (message.contact_id and reply.contact_id == message.contact_id)
                or (message.thread_id and reply.thread_id == message.thread_id)
            )
            for reply in outbound
        )
        if replied:
            continue
        due = _add_business_days(message.received_at.date(), rule.delay_business_days)
        if due > today:
            continue
        seed_key = f"fu-{str(message.id)[:8]}-rpl"
        existing = session.scalar(
            select(CampaignTask).where(
                CampaignTask.campaign_id == campaign.id, CampaignTask.seed_key == seed_key
            )
        )
        if existing:
            continue
        who = message.sender or "the sender"
        subject = message.subject or "(no subject)"
        session.add(
            CampaignTask(
                id=uuid4(),
                campaign_id=campaign.id,
                seed_key=seed_key,
                title=f"Reply to {who}: {subject}"[:500],
                category="follow_up",
                status="planned",
                priority="P0",
                due_date=due,
                estimated_minutes=15,
                pursuit_id=message.pursuit_id,
                communication_id=message.id,
                completion_criteria=(
                    f"No reply recorded within {rule.delay_business_days} business days of"
                    f" the message received {message.received_at.date().isoformat()}."
                    " Draft a reply, send it yourself, then log it as a sent communication."
                ),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        created += 1
    return created


@celery_app.task(bind=True, name="app.followup_tasks.evaluate_rules")
def evaluate_rules(self):
    try:
        with Session(get_engine()) as session, session.begin():
            return _evaluate_rules(session)
    except SQLAlchemyError:
        raise self.retry(
            exc=RuntimeError("Follow-up evaluation unavailable"), countdown=30, max_retries=2
        ) from None
