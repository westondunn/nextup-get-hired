"""Store normalized job listings and durable manual fetch runs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "job_fetches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("query", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("worker", sa.String(255)),
        sa.Column("received_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("stored_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(50)),
        sa.Column("error_message", sa.String(300)),
        sa.CheckConstraint("source IN ('sample', 'adzuna')", name="fetch_source"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'publish_failed')",
            name="fetch_status",
        ),
    )
    op.create_index(
        "ix_job_fetches_active_source",
        "job_fetches",
        ["source"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_table(
        "jobs",
        sa.Column("source", sa.String(20), primary_key=True),
        sa.Column("external_id", sa.String(200), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("company", sa.String(300), nullable=False),
        sa.Column("location", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("source IN ('sample', 'adzuna')", name="job_source"),
    )


def downgrade():
    op.drop_table("jobs")
    op.drop_table("job_fetches")
