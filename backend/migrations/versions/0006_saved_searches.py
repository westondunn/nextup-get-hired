"""Persist local dashboard searches without modifying profile or job data."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "saved_searches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("name_key", sa.String(240), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("include_expired", sa.Boolean(), nullable=False),
        sa.Column("filters", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("name_key", name="saved_search_name_key"),
        sa.CheckConstraint(
            "source IN ('sample', 'sample_greenhouse', 'sample_all', "
            "'adzuna', 'greenhouse', 'all')",
            name="saved_search_source",
        ),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM saved_searches")):
        raise RuntimeError("Saved searches exist; preserve/export them before downgrade.")
    op.drop_table("saved_searches")
