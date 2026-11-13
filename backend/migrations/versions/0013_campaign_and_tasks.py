"""Add campaign and campaign_tasks tables for structured search planning."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("campaign_key", sa.String(120), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(80), nullable=False, server_default="America/Chicago"),
        sa.Column("daily_capacity_minutes", sa.Integer(), nullable=False, server_default="240"),
        sa.Column("preferences", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("campaign_key", name="campaign_key_unique"),
        sa.CheckConstraint("end_date > start_date", name="campaign_date_order"),
    )
    op.create_table(
        "campaign_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "campaign_id",
            sa.Uuid(),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seed_key", sa.String(20)),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("category", sa.String(40), nullable=False, server_default="other"),
        sa.Column("status", sa.String(20), nullable=False, server_default="planned"),
        sa.Column("priority", sa.String(4), nullable=False, server_default="P1"),
        sa.Column("due_date", sa.Date()),
        sa.Column("estimated_minutes", sa.Integer()),
        sa.Column("depends_on", pg.JSONB(), nullable=False, server_default="[]"),
        sa.Column("suggested_after", pg.JSONB(), nullable=False, server_default="[]"),
        sa.Column("completion_criteria", sa.Text(), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "pursuit_id",
            sa.Uuid(),
            sa.ForeignKey("pursuits.id", ondelete="SET NULL"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "category IN ('administration','pipeline','planning','networking','resume',"
            "'profile','sourcing','applications','content','interview','follow_up',"
            "'review','evidence','other')",
            name="task_category",
        ),
        sa.CheckConstraint(
            "status IN ('planned','in_progress','waiting','blocked','completed','canceled')",
            name="task_status",
        ),
        sa.CheckConstraint("priority IN ('P0','P1','P2','P3')", name="task_priority"),
    )
    op.create_index(
        "ix_campaign_tasks_campaign_status_due",
        "campaign_tasks",
        ["campaign_id", "status", "due_date"],
    )
    # Partial unique index: seed_key unique per campaign where not null
    op.execute(
        "CREATE UNIQUE INDEX ix_campaign_tasks_seed_key "
        "ON campaign_tasks (campaign_id, seed_key) WHERE seed_key IS NOT NULL"
    )


def downgrade():
    op.drop_table("campaign_tasks")
    op.drop_table("campaigns")
