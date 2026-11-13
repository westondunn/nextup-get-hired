"""Contact and communication management."""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import companies
from app.application_detect import NOT_A_REPLY
from app.db import get_session
from app.email_classifications import HINT_KEY
from app.models import Communication, Company, Contact, Pursuit, PursuitEvent

router = APIRouter(tags=["contacts"])
Database = Annotated[Session, Depends(get_session)]

Relationship = Literal[
    "unknown", "recruiter", "hiring_manager", "referral", "colleague", "mentor", "friend", "other"
]
Channel = Literal["email", "linkedin", "phone", "in_person", "other"]
Direction = Literal["outbound", "inbound", "note"]
CommStatus = Literal["draft", "copied", "sent", "received", "private_note", "dismissed"]
ClassifierClass = Literal["new_application", "opportunity", "existing_company", "not_relevant"]


# ---------- Contacts ----------


class ContactInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    linkedin_url: str | None = Field(default=None, max_length=500)
    relationship: Relationship = "unknown"
    notes: str = Field(default="", max_length=4000)
    do_not_contact: bool = False
    introduced_by: str | None = Field(default=None, max_length=200)


class ContactUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    company: str | None = None
    title: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    relationship: Relationship | None = None
    notes: str | None = Field(default=None, max_length=4000)
    do_not_contact: bool | None = None
    introduced_by: str | None = None


def _contact_out(c: Contact) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "company": c.company,
        "title": c.title,
        "email": c.email,
        "phone": c.phone,
        "linkedin_url": c.linkedin_url,
        "relationship": c.relationship,
        "notes": c.notes,
        "do_not_contact": c.do_not_contact,
        "introduced_by": c.introduced_by,
        "last_contacted_at": c.last_contacted_at,
        "company_id": c.company_id,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }


@router.get("/api/contacts")
def list_contacts(session: Database, company: str | None = None, q: str | None = None):
    query = select(Contact).order_by(Contact.updated_at.desc())
    if company:
        query = query.where(Contact.company.ilike(f"%{company}%"))
    if q:
        query = query.where(
            Contact.name.ilike(f"%{q}%")
            | Contact.company.ilike(f"%{q}%")
            | Contact.title.ilike(f"%{q}%")
        )
    return [_contact_out(c) for c in session.scalars(query).all()]


@router.post("/api/contacts", status_code=201)
def create_contact(body: ContactInput, session: Database):
    now = datetime.now(UTC)
    row = Contact(id=uuid4(), **body.model_dump(), created_at=now, updated_at=now)
    session.add(row)
    companies.link_contact(session, row, now)
    session.commit()
    session.refresh(row)
    return _contact_out(row)


@router.get("/api/contacts/{contact_id}")
def read_contact(contact_id: UUID, session: Database):
    row = session.get(Contact, contact_id)
    if row is None:
        raise HTTPException(404, "Contact not found")
    return _contact_out(row)


@router.put("/api/contacts/{contact_id}")
def update_contact(contact_id: UUID, body: ContactUpdate, session: Database):
    row = session.get(Contact, contact_id)
    if row is None:
        raise HTTPException(404, "Contact not found")
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(row, key, value)
    row.updated_at = datetime.now(UTC)
    if "company" in body.model_fields_set:
        companies.link_contact(session, row, row.updated_at)
    session.commit()
    session.refresh(row)
    return _contact_out(row)


@router.delete("/api/contacts/{contact_id}", status_code=204)
def delete_contact(contact_id: UUID, session: Database):
    row = session.get(Contact, contact_id)
    if row is None:
        raise HTTPException(404, "Contact not found")
    company_id = row.company_id
    session.delete(row)
    session.flush()
    companies.refresh_status(session, company_id)
    session.commit()


# ---------- Communications ----------


class CommInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    # Identifiers arrive as JSON strings; strict mode must not reject them.
    contact_id: UUID | None = Field(default=None, strict=False)
    pursuit_id: UUID | None = Field(default=None, strict=False)
    campaign_task_id: UUID | None = Field(default=None, strict=False)
    channel: Channel = "email"
    direction: Direction = "outbound"
    subject: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=20000)
    status: CommStatus = "draft"
    notes: str = Field(default="", max_length=4000)
    # A logged reply keeps the imported message's thread so the exchange reads in order.
    thread_id: str | None = Field(default=None, max_length=200)


class CommUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    contact_id: UUID | None = Field(default=None, strict=False)
    pursuit_id: UUID | None = Field(default=None, strict=False)
    channel: Channel | None = None
    direction: Direction | None = None
    subject: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, max_length=20000)
    status: CommStatus | None = None
    sent_at: datetime | None = Field(default=None, strict=False)
    received_at: datetime | None = Field(default=None, strict=False)
    notes: str | None = Field(default=None, max_length=4000)


def _detection_out(detection: dict | None) -> dict | None:
    """Detection as the API returns it: the classifier's hint under a neutral key."""
    if not detection or HINT_KEY not in detection:
        return detection
    out = {key: value for key, value in detection.items() if key != HINT_KEY}
    out["classifier"] = detection[HINT_KEY]
    return out


def _comm_out(c: Communication) -> dict:
    return {
        "id": c.id,
        "contact_id": c.contact_id,
        "pursuit_id": c.pursuit_id,
        "campaign_task_id": c.campaign_task_id,
        "channel": c.channel,
        "direction": c.direction,
        "subject": c.subject,
        "body": c.body,
        "status": c.status,
        "sent_at": c.sent_at,
        "received_at": c.received_at,
        "notes": c.notes,
        "source": c.source,
        "source_id": c.source_id,
        "thread_id": c.thread_id,
        "sender": c.sender,
        "suggested_pursuit_id": c.suggested_pursuit_id,
        "detection": _detection_out(c.detection),
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }


@router.get("/api/communications")
def list_communications(
    session: Database,
    contact_id: UUID | None = None,
    pursuit_id: UUID | None = None,
    status: CommStatus | None = None,
    unlinked: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    classifier_classification: ClassifierClass | None = None,
    classifier_company_id: UUID | None = None,
    classifier_disagrees: bool = False,
):
    # Newest activity first by when the message was received or sent; imports from one
    # sync run share a created_at, so the id keeps pages stable.
    q = (
        select(Communication)
        .order_by(
            func.coalesce(
                Communication.received_at, Communication.sent_at, Communication.created_at
            ).desc(),
            Communication.id,
        )
        .limit(limit)
        .offset(offset)
    )
    if contact_id:
        q = q.where(Communication.contact_id == contact_id)
    if pursuit_id:
        q = q.where(Communication.pursuit_id == pursuit_id)
    if status:
        q = q.where(Communication.status == status)
    else:
        # Dismissed imports stay stored (so a re-scan cannot bring them back) but are
        # hidden everywhere unless asked for by status.
        q = q.where(Communication.status != "dismissed")
    # Filters over the external classifier's hint (see app/email_classifications.py).
    hint = Communication.detection[HINT_KEY]
    if classifier_classification:
        q = q.where(hint["classification"].astext == classifier_classification)
    if classifier_company_id:
        q = q.where(hint["company_id"].astext == str(classifier_company_id))
    if classifier_disagrees:
        q = q.where(hint["agrees"].astext == "false")
    if unlinked:
        # Review queue: imported mail that nobody has linked to a contact or pursuit yet.
        q = q.where(
            Communication.source != "manual",
            Communication.contact_id.is_(None),
            Communication.pursuit_id.is_(None),
        )
    rows = session.scalars(q).all()
    # Company names for linked and suggested pursuits so the UI can label both.
    wanted = {c.pursuit_id for c in rows if c.pursuit_id} | {
        c.suggested_pursuit_id for c in rows if c.suggested_pursuit_id
    }
    companies = {
        p.id: p.job.get("company", "")
        for p in session.scalars(select(Pursuit).where(Pursuit.id.in_(wanted))).all()
    }
    # The labeler's matched company, by its current name.
    hint_ids = {((c.detection or {}).get(HINT_KEY) or {}).get("company_id") for c in rows} - {None}
    matched = {
        str(company.id): company.name
        for company in session.scalars(
            select(Company).where(Company.id.in_([UUID(i) for i in hint_ids]))
        ).all()
    }
    return [
        {
            **_comm_out(c),
            "suggested_company": companies.get(c.suggested_pursuit_id),
            "pursuit_company": companies.get(c.pursuit_id),
            "classifier_company": matched.get(
                ((c.detection or {}).get(HINT_KEY) or {}).get("company_id") or ""
            ),
        }
        for c in rows
    ]


@router.post("/api/communications", status_code=201)
def create_communication(body: CommInput, session: Database):
    now = datetime.now(UTC)
    row = Communication(id=uuid4(), **body.model_dump(), created_at=now, updated_at=now)
    if body.status == "sent":
        row.sent_at = now
    if body.status == "received":
        row.received_at = now
    session.add(row)
    # Update contact's last_contacted_at
    if body.contact_id and body.status == "sent":
        contact = session.get(Contact, body.contact_id)
        if contact:
            contact.last_contacted_at = now
            contact.updated_at = now
    session.commit()
    session.refresh(row)
    return _comm_out(row)


@router.get("/api/communications/{comm_id}")
def read_communication(comm_id: UUID, session: Database):
    row = session.get(Communication, comm_id)
    if row is None:
        raise HTTPException(404, "Communication not found")
    return _comm_out(row)


@router.put("/api/communications/{comm_id}")
def update_communication(comm_id: UUID, body: CommUpdate, session: Database):
    row = session.get(Communication, comm_id)
    if row is None:
        raise HTTPException(404, "Communication not found")
    now = datetime.now(UTC)
    newly_linked = body.pursuit_id is not None and row.pursuit_id != body.pursuit_id
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(row, key, value)
    if newly_linked and row.direction == "inbound":
        if session.get(Pursuit, row.pursuit_id) is None:
            raise HTTPException(404, "Pursuit not found")
    automated = (row.detection or {}).get("kind") in NOT_A_REPLY
    if newly_linked and row.direction == "inbound" and not automated:
        # Lets the follow-up rules see a reply without changing the stage. Confirmations
        # and automatic replies are linked for the record but are not an answer.
        session.add(
            PursuitEvent(
                id=uuid4(),
                pursuit_id=row.pursuit_id,
                message=f"Received reply: {row.subject or '(no subject)'}"[:500],
                event_date=(row.received_at or now).date(),
                actor=row.sender or "",
                source=row.source,
                evidence=f"communication:{row.id}",
                created_at=now,
            )
        )
    if body.status == "sent" and not row.sent_at:
        row.sent_at = now
    if body.status == "received" and not row.received_at:
        row.received_at = now
    row.updated_at = now
    # Update contact's last_contacted_at when marking sent
    if body.status == "sent" and row.contact_id:
        contact = session.get(Contact, row.contact_id)
        if contact:
            contact.last_contacted_at = now
            contact.updated_at = now
    session.commit()
    session.refresh(row)
    return _comm_out(row)
