"""Add attachments JSONB to pursuit_events for transcripts, files, and references."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "pursuit_events",
        sa.Column("attachments", pg.JSONB(), server_default="[]", nullable=False),
    )


def downgrade():
    op.drop_column("pursuit_events", "attachments")
