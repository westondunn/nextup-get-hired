"""Add structured prep_data and offer_data JSONB columns to pursuits, and
application_template / outreach_template to career_settings."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "pursuits",
        sa.Column("prep_data", pg.JSONB(), server_default="{}", nullable=False),
    )
    op.add_column(
        "pursuits",
        sa.Column("offer_data", pg.JSONB(), server_default="{}", nullable=False),
    )
    op.add_column(
        "career_settings",
        sa.Column("application_template", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "career_settings",
        sa.Column("outreach_template", sa.Text(), server_default="", nullable=False),
    )


def downgrade():
    op.drop_column("career_settings", "outreach_template")
    op.drop_column("career_settings", "application_template")
    op.drop_column("pursuits", "offer_data")
    op.drop_column("pursuits", "prep_data")
