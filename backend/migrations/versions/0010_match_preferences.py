"""Local discovery relevance preferences; preserve configured rules on rollback."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "discovery_settings",
        sa.Column("match_preferences", postgresql.JSONB(), server_default="{}", nullable=False),
    )


def downgrade():
    connection = op.get_bind()
    if connection.scalar(
        sa.text("SELECT count(*) FROM discovery_settings WHERE match_preferences <> '{}'::jsonb")
    ):
        raise RuntimeError("Match preferences exist; preserve them before downgrade.")
    if connection.scalar(
        sa.text("SELECT count(*) FROM saved_searches WHERE filters ? 'discovery_only'")
    ):
        raise RuntimeError("Discovery-filter searches exist; preserve them before downgrade.")
    op.drop_column("discovery_settings", "match_preferences")
