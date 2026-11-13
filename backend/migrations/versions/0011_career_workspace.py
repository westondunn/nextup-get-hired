"""Persist local planning, application tracking, drafts and activity history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "career_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("preferences", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column("worker", sa.String(255)),
        sa.Column("status", sa.String(30), nullable=False, server_default="not_run"),
        sa.CheckConstraint("id=1", name="single_career_settings"),
    )
    op.create_table(
        "pursuits",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_key", sa.String(64), nullable=False),
        sa.Column("job", pg.JSONB(), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False, server_default="review"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("application_draft", sa.Text(), nullable=False, server_default=""),
        sa.Column("outreach_draft", sa.Text(), nullable=False, server_default=""),
        sa.Column("next_action_on", sa.Date()),
        sa.Column("created_by", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("job_key", name="pursuit_job_key"),
        sa.CheckConstraint("version >= 1", name="pursuit_version"),
        sa.CheckConstraint(
            "stage IN ('review','preparing','applied','interview','offer','accepted',"
            "'rejected','withdrawn','dismissed')",
            name="pursuit_stage",
        ),
    )
    op.create_table(
        "pursuit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "pursuit_id",
            sa.Uuid(),
            sa.ForeignKey("pursuits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_pursuit_events_pursuit_id", "pursuit_events", ["pursuit_id"])


def downgrade():
    connection = op.get_bind()
    for table in ("career_settings", "pursuits", "pursuit_events"):
        if connection.scalar(sa.text(f"SELECT count(*) FROM {table}")):
            raise RuntimeError("Career workspace data exists; preserve it before downgrade.")
    op.drop_table("pursuit_events")
    op.drop_table("pursuits")
    op.drop_table("career_settings")
