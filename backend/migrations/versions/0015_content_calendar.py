"""Add content_items table for the content calendar."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "content_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("seed_key", sa.String(20)),
        sa.Column("kind", sa.String(30), nullable=False, server_default="linkedin_post"),
        sa.Column("state", sa.String(20), nullable=False, server_default="idea"),
        sa.Column("topic", sa.String(500), nullable=False),
        sa.Column("title", sa.String(500)),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("outline", pg.JSONB()),
        sa.Column(
            "campaign_task_id",
            sa.Uuid(),
            sa.ForeignKey("campaign_tasks.id", ondelete="SET NULL"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("public_url", sa.String(2048)),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "kind IN ('linkedin_post','article','comment','other')",
            name="content_kind",
        ),
        sa.CheckConstraint(
            "state IN ('idea','outline','draft','approved','scheduled','published')",
            name="content_state",
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_content_items_seed_key "
        "ON content_items (seed_key) WHERE seed_key IS NOT NULL"
    )


def downgrade():
    op.drop_table("content_items")
