from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

orm_relationship = relationship


class Base(DeclarativeBase):
    pass


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (CheckConstraint("id = 1", name="single_profile"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    skills: Mapped[list[str]] = mapped_column(ARRAY(String(100)))
    target_titles: Mapped[list[str]] = mapped_column(ARRAY(String(120)))
    location: Mapped[str] = mapped_column(String(160))
    work_preferences: Mapped[list[str]] = mapped_column(ARRAY(String(10)))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DiagnosticRun(Base):
    __tablename__ = "diagnostic_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'succeeded', 'publish_failed', 'failed')", name="run_status"
        ),
        CheckConstraint("source IN ('manual', 'scheduler')", name="run_source"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    worker: Mapped[str | None] = mapped_column(String(255))
    result: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(String(300))
    recovery_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_attempts: Mapped[int] = mapped_column(default=0, server_default="0")


class JobFetch(Base):
    __tablename__ = "job_fetches"
    __table_args__ = (
        CheckConstraint(
            "source IN ('adzuna', 'greenhouse', 'lever', 'ashby', 'reference')",
            name="fetch_source",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'publish_failed')",
            name="fetch_status",
        ),
        Index(
            "ix_job_fetches_active_source",
            "source",
            "board_key",
            unique=True,
            postgresql_where=text(
                "status IN ('queued', 'running') OR "
                "(status = 'publish_failed' AND recovery_deadline IS NOT NULL)"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    board_key: Mapped[str] = mapped_column(String(100), default="", server_default="")
    query: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker: Mapped[str | None] = mapped_column(String(255))
    received_count: Mapped[int] = mapped_column(default=0, server_default="0")
    stored_count: Mapped[int] = mapped_column(default=0, server_default="0")
    skipped_count: Mapped[int] = mapped_column(default=0, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(String(300))
    recovery_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    execution_token: Mapped[UUID | None]
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "source IN ('adzuna', 'greenhouse', 'lever', 'ashby', 'reference')",
            name="job_source",
        ),
        CheckConstraint("score IS NULL OR score BETWEEN 0 AND 100", name="job_score_range"),
    )

    source: Mapped[str] = mapped_column(String(20), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    company: Mapped[str] = mapped_column(String(300))
    location: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(2048))
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    dedupe_key: Mapped[str] = mapped_column(String(64), index=True)
    date_kind: Mapped[str] = mapped_column(String(8), default="posted", server_default="posted")
    score: Mapped[int | None]
    score_breakdown: Mapped[dict | None] = mapped_column(JSONB)
    score_signature: Mapped[str | None] = mapped_column(String(64))


EMAIL_CLASSES = ("new_application", "opportunity", "existing_company", "not_relevant")


class EmailClassification(Base):
    """An external classifier's verdict on one Gmail message; a hint the sync merges into detection.

    Written by the classifier (contract in docs/CORRESPONDENCE_SYNC.md), read and stamped by Nextup.
    """

    __tablename__ = "email_classifications"
    __table_args__ = (
        CheckConstraint(
            "classification IN ('new_application','opportunity','existing_company','not_relevant')",
            name="email_classification_value",
        ),
        Index("ix_email_classifications_company_id", "company_id"),
        Index(
            "ix_email_classifications_unapplied",
            "classified_at",
            postgresql_where=text("applied_at IS NULL"),
        ),
    )

    gmail_message_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    thread_id: Mapped[str | None] = mapped_column(String(200))
    classification: Mapped[str] = mapped_column(String(30))
    companies: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("'{}'::text[]")
    )
    company_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "companies.id", ondelete="SET NULL", name="email_classifications_company_id_fkey"
        )
    )
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobRating(Base):
    """ "More like this" / "less like this" on one grouped job; tunes scoring.

    Title and company are copied so the rating keeps teaching after the job expires.
    """

    __tablename__ = "job_ratings"
    __table_args__ = (
        UniqueConstraint("job_key", name="job_rating_job_key"),
        CheckConstraint("rating IN (-1, 1)", name="job_rating_value"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    # jobs.dedupe_key: one rating covers every source carrying the same posting.
    job_key: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(500))
    company: Mapped[str] = mapped_column(String(300))
    rating: Mapped[int] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SavedSearch(Base):
    __tablename__ = "saved_searches"
    __table_args__ = (
        UniqueConstraint("name_key", name="saved_search_name_key"),
        CheckConstraint("alert_min_score BETWEEN 0 AND 100", name="alert_min_score_range"),
        CheckConstraint(
            "source IN ('adzuna', 'greenhouse', 'lever', 'ashby', 'reference', 'all')",
            name="saved_search_source",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    name_key: Mapped[str] = mapped_column(String(240))
    source: Mapped[str] = mapped_column(String(20))
    include_expired: Mapped[bool] = mapped_column(default=False)
    filters: Mapped[dict] = mapped_column(JSONB)
    alerts_enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    alert_min_score: Mapped[int] = mapped_column(default=70, server_default="70")
    alert_check_status: Mapped[str] = mapped_column(
        String(30), default="disabled", server_default="disabled"
    )
    alert_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alert_worker: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobAlert(Base):
    __tablename__ = "job_alerts"
    __table_args__ = (UniqueConstraint("search_id", "job_key", name="alert_search_job_key"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    search_id: Mapped[UUID] = mapped_column(ForeignKey("saved_searches.id", ondelete="CASCADE"))
    job_key: Mapped[str] = mapped_column(String(64))
    search_name: Mapped[str] = mapped_column(String(80))
    job: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DiscoverySettings(Base):
    __tablename__ = "discovery_settings"
    __table_args__ = (
        CheckConstraint("id=1", name="single_discovery_settings"),
        CheckConstraint("interval_hours BETWEEN 6 AND 168", name="discovery_interval"),
        CheckConstraint("min_score BETWEEN 0 AND 100", name="discovery_score"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    interval_hours: Mapped[int] = mapped_column(default=24, server_default="24")
    min_score: Mapped[int] = mapped_column(default=20, server_default="20")
    boards: Mapped[list[dict]] = mapped_column(JSONB)
    match_preferences: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CareerSettings(Base):
    __tablename__ = "career_settings"
    __table_args__ = (CheckConstraint("id=1", name="single_career_settings"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    preferences: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30), default="not_run", server_default="not_run")
    application_template: Mapped[str] = mapped_column(Text, default="", server_default="")
    outreach_template: Mapped[str] = mapped_column(Text, default="", server_default="")


class Pursuit(Base):
    __tablename__ = "pursuits"
    __table_args__ = (
        UniqueConstraint("job_key", name="pursuit_job_key"),
        CheckConstraint(
            "stage IN ('review','preparing','applied','interview','offer','accepted',"
            "'rejected','withdrawn','dismissed')",
            name="pursuit_stage",
        ),
        CheckConstraint("version >= 1", name="pursuit_version"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    job_key: Mapped[str] = mapped_column(String(64))
    job: Mapped[dict] = mapped_column(JSONB)
    stage: Mapped[str] = mapped_column(String(20), default="review", server_default="review")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    application_draft: Mapped[str] = mapped_column(Text, default="", server_default="")
    outreach_draft: Mapped[str] = mapped_column(Text, default="", server_default="")
    next_action_on: Mapped[date | None] = mapped_column(Date)
    created_by: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(default=1, server_default="1")
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prep_data: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    offer_data: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    # Which resume file went with this application; the version row outlives the link.
    resume_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("resume_versions.id", ondelete="SET NULL"), index=True
    )
    resume_version: Mapped["ResumeVersion | None"] = relationship(lazy="select")
    # Canonical employer; job["company"] keeps the text the listing carried.
    company_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL", name="pursuits_company_id_fkey"),
        index=True,
    )
    company: Mapped["Company | None"] = relationship(back_populates="pursuits", lazy="select")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PursuitEvent(Base):
    __tablename__ = "pursuit_events"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    pursuit_id: Mapped[UUID] = mapped_column(
        ForeignKey("pursuits.id", ondelete="CASCADE"), index=True
    )
    message: Mapped[str] = mapped_column(String(500))
    event_date: Mapped[date | None] = mapped_column(Date)
    actor: Mapped[str | None] = mapped_column(String(200), server_default="")
    source: Mapped[str | None] = mapped_column(String(200), server_default="")
    evidence: Mapped[str | None] = mapped_column(String(500), server_default="")
    attachments: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Campaign(Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        UniqueConstraint("campaign_key", name="campaign_key_unique"),
        CheckConstraint("end_date > start_date", name="campaign_date_order"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    campaign_key: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(300))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    timezone: Mapped[str] = mapped_column(
        String(80), default="UTC", server_default="America/Chicago"
    )
    daily_capacity_minutes: Mapped[int] = mapped_column(Integer, default=240, server_default="240")
    preferences: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CampaignTask(Base):
    __tablename__ = "campaign_tasks"
    __table_args__ = (
        CheckConstraint(
            "category IN ('administration','pipeline','planning','networking','resume',"
            "'profile','sourcing','applications','content','interview','follow_up',"
            "'review','evidence','other')",
            name="task_category",
        ),
        CheckConstraint(
            "status IN ('planned','in_progress','waiting','blocked','completed','canceled')",
            name="task_status",
        ),
        CheckConstraint("priority IN ('P0','P1','P2','P3')", name="task_priority"),
        Index("ix_campaign_tasks_campaign_status_due", "campaign_id", "status", "due_date"),
        Index(
            "ix_campaign_tasks_seed_key",
            "campaign_id",
            "seed_key",
            unique=True,
            postgresql_where=text("seed_key IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    campaign_id: Mapped[UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    seed_key: Mapped[str | None] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(40), default="other", server_default="other")
    status: Mapped[str] = mapped_column(String(20), default="planned", server_default="planned")
    priority: Mapped[str] = mapped_column(String(4), default="P1", server_default="P1")
    due_date: Mapped[date | None] = mapped_column(Date)
    estimated_minutes: Mapped[int | None] = mapped_column(Integer)
    depends_on: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    suggested_after: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    completion_criteria: Mapped[str] = mapped_column(Text, default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    pursuit_id: Mapped[UUID | None] = mapped_column(ForeignKey("pursuits.id", ondelete="SET NULL"))
    # The imported message a follow-up task answers, so the task can show it in full.
    communication_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("communications.id", ondelete="SET NULL"), index=True
    )
    communication: Mapped["Communication | None"] = relationship(
        foreign_keys=[communication_id], lazy="select"
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('needs_user_confirmation','confirmed','rejected')",
            name="evidence_verification_status",
        ),
        Index(
            "ix_evidence_seed_key",
            "seed_key",
            unique=True,
            postgresql_where=text("seed_key IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    seed_key: Mapped[str | None] = mapped_column(String(20))
    topic: Mapped[str] = mapped_column(String(500))
    detail: Mapped[str] = mapped_column(Text, default="", server_default="")
    verification_status: Mapped[str] = mapped_column(
        String(30), default="needs_user_confirmation", server_default="needs_user_confirmation"
    )
    source: Mapped[str | None] = mapped_column(String(300))
    scope: Mapped[str | None] = mapped_column(String(300))
    dates: Mapped[str | None] = mapped_column(String(100))
    personal_contribution: Mapped[str] = mapped_column(Text, default="", server_default="")
    permitted_wording: Mapped[str] = mapped_column(Text, default="", server_default="")
    instruction: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResumeVersion(Base):
    __tablename__ = "resume_versions"
    __table_args__ = (
        UniqueConstraint("variant_name", "version_number", name="resume_variant_version"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    variant_name: Mapped[str] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(Text, default="", server_default="")
    version_number: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    # The uploaded PDF or DOCX as submitted; bytes stay deferred so listings never load them.
    file_name: Mapped[str | None] = mapped_column(String(255))
    file_type: Mapped[str | None] = mapped_column(String(100))
    file_size: Mapped[int | None] = mapped_column(Integer)
    file_uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    file_data: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContentItem(Base):
    __tablename__ = "content_items"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('linkedin_post','article','comment','other')", name="content_kind"
        ),
        CheckConstraint(
            "state IN ('idea','outline','draft','approved','scheduled','published')",
            name="content_state",
        ),
        Index(
            "ix_content_items_seed_key",
            "seed_key",
            unique=True,
            postgresql_where=text("seed_key IS NOT NULL"),
        ),
        Index("ix_content_items_series", "series", postgresql_where=text("series IS NOT NULL")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    seed_key: Mapped[str | None] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(
        String(30), default="linkedin_post", server_default="linkedin_post"
    )
    state: Mapped[str] = mapped_column(String(20), default="idea", server_default="idea")
    topic: Mapped[str] = mapped_column(String(500))
    title: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text, default="", server_default="")
    outline: Mapped[dict | None] = mapped_column(JSONB)
    campaign_task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("campaign_tasks.id", ondelete="SET NULL")
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    public_url: Mapped[str | None] = mapped_column(String(2048))
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    target_date: Mapped[date | None] = mapped_column(Date)
    series: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    campaign_task: Mapped["CampaignTask | None"] = relationship(lazy="raise_on_sql")


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        CheckConstraint(
            "relationship IN ('unknown','recruiter','hiring_manager','referral','colleague',"
            "'mentor','friend','other')",
            name="contact_relationship",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    company: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(40))
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    relationship: Mapped[str] = mapped_column(
        String(40), default="unknown", server_default="unknown"
    )
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    introduced_by: Mapped[str | None] = mapped_column(String(200))
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Canonical employer; the free-text company column is kept as entered.
    company_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL", name="contacts_company_id_fkey"),
        index=True,
    )
    # Contact has a column named "relationship", which shadows the function here.
    company_record: Mapped["Company | None"] = orm_relationship(
        back_populates="contacts", lazy="select"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


COMPANY_STATUSES = ("tracking", "applied", "interviewing", "contact_only", "archived")


class Company(Base):
    """One employer. Queried directly by an external email classifier: keep column names stable."""

    __tablename__ = "companies"
    __table_args__ = (
        CheckConstraint(
            "status IN ('tracking','applied','interviewing','contact_only','archived')",
            name="company_status",
        ),
        Index("ux_companies_name_normalized", "name_normalized", unique=True),
        Index("ix_companies_aliases", "aliases", postgresql_using="gin"),
        Index("ix_companies_domains", "domains", postgresql_using="gin"),
        Index(
            "ix_companies_name_normalized_trgm",
            "name_normalized",
            postgresql_using="gin",
            postgresql_ops={"name_normalized": "gin_trgm_ops"},
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    # Computed by the database function from migration 0027; never written by the app.
    name_normalized: Mapped[str] = mapped_column(
        Text, Computed("nextup_normalize_company(name)", persisted=True)
    )
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("'{}'::text[]")
    )
    domains: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("'{}'::text[]")
    )
    status: Mapped[str] = mapped_column(Text, default="tracking", server_default="tracking")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    pursuits: Mapped[list["Pursuit"]] = relationship(
        back_populates="company", passive_deletes=True, lazy="select"
    )
    contacts: Mapped[list["Contact"]] = relationship(
        back_populates="company_record", passive_deletes=True, lazy="select"
    )


class Communication(Base):
    __tablename__ = "communications"
    __table_args__ = (
        CheckConstraint(
            "channel IN ('email','linkedin','phone','in_person','other')", name="comm_channel"
        ),
        CheckConstraint("direction IN ('outbound','inbound','note')", name="comm_direction"),
        CheckConstraint(
            "status IN ('draft','copied','sent','received','private_note','dismissed')",
            name="comm_status",
        ),
        Index("ix_communications_contact_id", "contact_id"),
        Index("ix_communications_pursuit_id", "pursuit_id"),
        Index(
            "ux_communications_source_id",
            "source",
            "source_id",
            unique=True,
            postgresql_where=text("source_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    contact_id: Mapped[UUID | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    pursuit_id: Mapped[UUID | None] = mapped_column(ForeignKey("pursuits.id", ondelete="SET NULL"))
    campaign_task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("campaign_tasks.id", ondelete="SET NULL")
    )
    channel: Mapped[str] = mapped_column(String(30), default="email", server_default="email")
    direction: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft")
    subject: Mapped[str] = mapped_column(String(500), default="", server_default="")
    body: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Correspondence sync provenance; manual rows keep source="manual" and no source_id.
    source: Mapped[str] = mapped_column(String(20), default="manual", server_default="manual")
    source_id: Mapped[str | None] = mapped_column(String(200))
    thread_id: Mapped[str | None] = mapped_column(String(200))
    sender: Mapped[str | None] = mapped_column(String(320))
    suggested_pursuit_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("pursuits.id", ondelete="SET NULL")
    )
    # Local classification of imported mail (application_detect); NULL until classified.
    detection: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CorrespondenceSyncSettings(Base):
    """Singleton configuration and cursor for the read-only Gmail sync."""

    __tablename__ = "correspondence_sync_settings"
    __table_args__ = (
        CheckConstraint("id=1", name="single_correspondence_sync_settings"),
        CheckConstraint("max_messages_per_run BETWEEN 1 AND 200", name="correspondence_batch"),
        CheckConstraint("calendar_lookahead_days BETWEEN 1 AND 60", name="calendar_lookahead"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    query: Mapped[str] = mapped_column(
        String(500), default="label:job-search", server_default="label:job-search"
    )
    max_messages_per_run: Mapped[int] = mapped_column(Integer, default=25, server_default="25")
    cursor_epoch: Mapped[int | None] = mapped_column(BigInteger)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str] = mapped_column(
        String(30), default="not_run", server_default="not_run"
    )
    last_error: Mapped[str] = mapped_column(Text, default="", server_default="")
    last_imported: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Create or advance an application when a confirmation email is recognized.
    auto_create_applications: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    calendar_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    calendar_lookahead_days: Mapped[int] = mapped_column(Integer, default=14, server_default="14")
    calendar_last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calendar_last_status: Mapped[str] = mapped_column(
        String(30), default="not_run", server_default="not_run"
    )
    calendar_last_error: Mapped[str] = mapped_column(Text, default="", server_default="")
    calendar_last_imported: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FollowUpRule(Base):
    __tablename__ = "follow_up_rules"
    __table_args__ = (UniqueConstraint("rule_key", name="follow_up_rule_key_unique"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    rule_key: Mapped[str] = mapped_column(String(60))
    trigger: Mapped[str] = mapped_column(String(80))
    delay_business_days: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    action: Mapped[str] = mapped_column(
        String(40), default="create_review_task", server_default="create_review_task"
    )
    contact_required_for_outreach: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
