"""Import campaign seed data with preview and idempotent upsert."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import companies
from app.db import get_session
from app.models import Campaign, CampaignTask, Contact, ContentItem, Evidence, FollowUpRule

router = APIRouter(prefix="/api/seed", tags=["seed import"])
Database = Annotated[Session, Depends(get_session)]


class SeedPayload(BaseModel):
    class Config:
        extra = "allow"


@router.post("/preview")
def preview_seed(body: dict, session: Database):
    campaign_data = body.get("campaign", {})
    tasks_data = body.get("tasks", [])
    evidence_data = body.get("candidate_evidence", [])
    content_data = body.get("content", [])
    leads_data = body.get("lead_reconciliation", [])

    campaign_key = campaign_data.get("campaign_key", "")
    existing_campaign = (
        session.scalar(select(Campaign).where(Campaign.campaign_key == campaign_key))
        if campaign_key
        else None
    )

    # Check existing tasks by seed_key
    existing_task_keys: set[str] = set()
    if existing_campaign:
        rows = session.scalars(
            select(CampaignTask).where(
                CampaignTask.campaign_id == existing_campaign.id, CampaignTask.seed_key.isnot(None)
            )
        ).all()
        existing_task_keys = {r.seed_key for r in rows if r.seed_key}

    new_tasks = []
    updated_tasks = []
    skipped_tasks = []
    for t in tasks_data:
        sk = t.get("seed_key")
        if sk in existing_task_keys:
            # Check if completed or canceled — skip those
            row = session.scalar(
                select(CampaignTask).where(
                    CampaignTask.campaign_id == existing_campaign.id,
                    CampaignTask.seed_key == sk,
                )
            )
            if row and row.status in ("completed", "canceled"):
                skipped_tasks.append(
                    {"seed_key": sk, "title": t.get("title"), "reason": f"Already {row.status}"}
                )
            else:
                updated_tasks.append({"seed_key": sk, "title": t.get("title")})
        else:
            new_tasks.append({"seed_key": sk, "title": t.get("title")})

    # Lead reconciliation tasks
    for lead in leads_data:
        task_sk = lead.get("task_seed_key")
        if task_sk and task_sk not in existing_task_keys:
            new_tasks.append(
                {
                    "seed_key": task_sk,
                    "title": f"Reconcile lead: {lead.get('company', 'unknown')}",
                    "from_lead": True,
                }
            )

    return {
        "campaign": {
            "key": campaign_key,
            "exists": existing_campaign is not None,
            "action": "update" if existing_campaign else "create",
        },
        "tasks": {
            "new": len(new_tasks),
            "updated": len(updated_tasks),
            "skipped": len(skipped_tasks),
            "details": {
                "new": new_tasks[:20],
                "updated": updated_tasks[:20],
                "skipped": skipped_tasks[:20],
            },
        },
        "evidence": {"count": len(evidence_data)},
        "content": {"count": len(content_data)},
        "leads": {"count": len(leads_data)},
        "contacts": {"count": len(body.get("contacts", []))},
    }


@router.post("/apply")
def apply_seed(body: dict, session: Database):
    now = datetime.now(UTC)
    campaign_data = body.get("campaign", {})
    tasks_data = body.get("tasks", [])
    body.get("lead_reconciliation", [])

    # Upsert campaign
    campaign_key = campaign_data.get("campaign_key")
    if not campaign_key:
        raise HTTPException(422, "campaign.campaign_key is required")

    campaign = session.scalar(select(Campaign).where(Campaign.campaign_key == campaign_key))
    if campaign:
        campaign.title = campaign_data.get("title", campaign.title)
        campaign.start_date = campaign_data.get("start_date", campaign.start_date)
        campaign.end_date = campaign_data.get("end_date", campaign.end_date)
        campaign.timezone = campaign_data.get("timezone", campaign.timezone)
        campaign.daily_capacity_minutes = campaign_data.get(
            "daily_capacity_minutes", campaign.daily_capacity_minutes
        )
        prefs = dict(campaign.preferences)
        for key in (
            "tracks",
            "weekly_targets",
            "monthly_targets",
            "preferences",
            "working_weekdays",
            "planned_low_availability_dates",
            "excluded_follow_up_dates",
        ):
            if key in campaign_data:
                prefs[key] = campaign_data[key]
        campaign.preferences = prefs
        campaign.updated_at = now
    else:
        prefs = {}
        for key in (
            "tracks",
            "weekly_targets",
            "monthly_targets",
            "preferences",
            "working_weekdays",
            "planned_low_availability_dates",
            "excluded_follow_up_dates",
            "capacity_caps_are_included_in_total",
            "targets_are",
            "portal_cap_includes_setup",
        ):
            if key in campaign_data:
                prefs[key] = campaign_data[key]
        campaign = Campaign(
            id=uuid4(),
            campaign_key=campaign_key,
            title=campaign_data.get("title", "Job Search Campaign"),
            start_date=campaign_data.get("start_date"),
            end_date=campaign_data.get("end_date"),
            timezone=campaign_data.get("timezone", "UTC"),
            daily_capacity_minutes=campaign_data.get("daily_capacity_minutes", 240),
            preferences=prefs,
            created_at=now,
            updated_at=now,
        )
        session.add(campaign)
    session.flush()

    # Upsert tasks
    created = 0
    updated = 0
    skipped = 0
    for t in tasks_data:
        sk = t.get("seed_key")
        existing = None
        if sk:
            existing = session.scalar(
                select(CampaignTask).where(
                    CampaignTask.campaign_id == campaign.id,
                    CampaignTask.seed_key == sk,
                )
            )
        if existing:
            if existing.status in ("completed", "canceled"):
                skipped += 1
                continue
            existing.title = t.get("title", existing.title)
            existing.category = t.get("category", existing.category)
            existing.priority = t.get("priority", existing.priority)
            if t.get("due_date") and not existing.notes:  # Don't overwrite user edits
                existing.due_date = t["due_date"]
            if t.get("estimated_minutes"):
                existing.estimated_minutes = t["estimated_minutes"]
            if t.get("completion_criteria"):
                existing.completion_criteria = t["completion_criteria"]
            if t.get("depends_on"):
                existing.depends_on = t["depends_on"]
            if t.get("suggested_after"):
                existing.suggested_after = t["suggested_after"]
            existing.updated_at = now
            updated += 1
        else:
            task = CampaignTask(
                id=uuid4(),
                campaign_id=campaign.id,
                seed_key=sk,
                title=t.get("title", "Untitled task"),
                category=t.get("category", "other"),
                status=t.get("status", "planned"),
                priority=t.get("priority", "P1"),
                due_date=t.get("due_date"),
                estimated_minutes=t.get("estimated_minutes"),
                depends_on=t.get("depends_on", []),
                suggested_after=t.get("suggested_after", []),
                completion_criteria=t.get("completion_criteria", ""),
                created_at=now,
                updated_at=now,
            )
            session.add(task)
            created += 1

    # Evidence
    evidence_data = body.get("candidate_evidence", [])
    evidence_created = 0
    for ev in evidence_data:
        sk = ev.get("seed_key")
        existing_ev = None
        if sk:
            existing_ev = session.scalar(select(Evidence).where(Evidence.seed_key == sk))
        if existing_ev:
            if existing_ev.verification_status == "confirmed":
                continue  # Never downgrade confirmed evidence
            if ev.get("topic"):
                existing_ev.topic = ev["topic"]
            if ev.get("instruction"):
                existing_ev.instruction = ev["instruction"]
            existing_ev.updated_at = now
        else:
            row = Evidence(
                id=uuid4(),
                seed_key=sk,
                topic=ev.get("topic", ""),
                verification_status=ev.get("verification_status", "needs_user_confirmation"),
                instruction=ev.get("instruction", ""),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            evidence_created += 1

    # Content items
    content_data = body.get("content", [])
    content_created = 0
    # Build task seed_key → task id map for linking
    task_map: dict[str, UUID] = {}
    for t in session.scalars(
        select(CampaignTask).where(
            CampaignTask.campaign_id == campaign.id,
            CampaignTask.seed_key.isnot(None),
        )
    ).all():
        if t.seed_key:
            task_map[t.seed_key] = t.id

    for ci in content_data:
        sk = ci.get("seed_key")
        existing_ci = None
        if sk:
            existing_ci = session.scalar(select(ContentItem).where(ContentItem.seed_key == sk))
        if existing_ci:
            if existing_ci.state == "published":
                continue  # Never downgrade published content
            if ci.get("topic"):
                existing_ci.topic = ci["topic"]
            if ci.get("body") and not existing_ci.body:
                existing_ci.body = ci["body"]
            if ci.get("outline") and not existing_ci.outline:
                existing_ci.outline = ci["outline"]
            if ci.get("title") and not existing_ci.title:
                existing_ci.title = ci["title"]
            if ci.get("target_date") and not existing_ci.target_date:
                existing_ci.target_date = ci["target_date"]
            if ci.get("series") and not existing_ci.series:
                existing_ci.series = ci["series"]
            task_sk = ci.get("task_seed_key")
            if task_sk and task_sk in task_map and not existing_ci.campaign_task_id:
                existing_ci.campaign_task_id = task_map[task_sk]
            existing_ci.updated_at = now
        else:
            task_sk = ci.get("task_seed_key")
            row = ContentItem(
                id=uuid4(),
                seed_key=sk,
                kind=ci.get("kind", "linkedin_post"),
                state=ci.get("state", "idea"),
                topic=ci.get("topic", ""),
                title=ci.get("title"),
                body=ci.get("body", ""),
                outline=ci.get("outline"),
                campaign_task_id=task_map.get(task_sk) if task_sk else None,
                target_date=ci.get("target_date"),
                series=ci.get("series"),
                notes=ci.get("notes", ""),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            content_created += 1

    # Contacts
    contacts_data = body.get("contacts", [])
    contacts_created = 0
    for ct in contacts_data:
        name = ct.get("name", "").strip()
        if not name:
            continue
        # Skip duplicates by name + company
        existing_ct = session.scalar(
            select(Contact).where(
                Contact.name == name,
                Contact.company == ct.get("company"),
            )
        )
        if existing_ct:
            # Update notes if richer
            if ct.get("notes") and len(ct["notes"]) > len(existing_ct.notes or ""):
                existing_ct.notes = ct["notes"]
                existing_ct.updated_at = now
            continue
        row = Contact(
            id=uuid4(),
            name=name,
            company=ct.get("company"),
            title=ct.get("title"),
            email=ct.get("email"),
            phone=ct.get("phone"),
            linkedin_url=ct.get("linkedin_url"),
            relationship=ct.get("relationship", "unknown"),
            notes=ct.get("notes", ""),
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        companies.link_contact(session, row, now)
        contacts_created += 1

    # Follow-up rules
    rules_data = body.get("follow_up_defaults", [])
    rules_created = 0
    for rule in rules_data:
        rk = rule.get("rule_key")
        if not rk:
            continue
        existing_rule = session.scalar(select(FollowUpRule).where(FollowUpRule.rule_key == rk))
        if existing_rule:
            existing_rule.trigger = rule.get("trigger", existing_rule.trigger)
            existing_rule.delay_business_days = rule.get(
                "delay_business_days", existing_rule.delay_business_days
            )
            existing_rule.action = rule.get("action", existing_rule.action)
            existing_rule.contact_required_for_outreach = rule.get(
                "contact_required_for_outreach",
                existing_rule.contact_required_for_outreach,
            )
            final_key = "optional_final_follow_up_business_days_after_first"
            if rule.get(final_key):
                existing_rule.config = {
                    **existing_rule.config,
                    "final_follow_up": rule[final_key],
                }
            existing_rule.updated_at = now
        else:
            config = {}
            final_key = "optional_final_follow_up_business_days_after_first"
            if rule.get(final_key):
                config["final_follow_up"] = rule[final_key]
            row = FollowUpRule(
                id=uuid4(),
                rule_key=rk,
                trigger=rule.get("trigger", ""),
                delay_business_days=rule.get("delay_business_days", 5),
                action=rule.get("action", "create_review_task"),
                contact_required_for_outreach=rule.get("contact_required_for_outreach", False),
                config=config,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            rules_created += 1

    session.commit()
    return {
        "campaign_id": str(campaign.id),
        "campaign_key": campaign.campaign_key,
        "tasks_created": created,
        "tasks_updated": updated,
        "tasks_skipped": skipped,
        "evidence_created": evidence_created,
        "content_created": content_created,
        "contacts_created": contacts_created,
        "rules_created": rules_created,
    }
