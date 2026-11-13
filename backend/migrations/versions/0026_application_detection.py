"""Classify imported mail and allow applications to be created from confirmations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("communications", sa.Column("detection", postgresql.JSONB()))
    op.add_column(
        "correspondence_sync_settings",
        sa.Column(
            "auto_create_applications",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade():
    # Applications and contacts created from mail are ordinary rows and stay in place.
    op.drop_column("correspondence_sync_settings", "auto_create_applications")
    op.drop_column("communications", "detection")
