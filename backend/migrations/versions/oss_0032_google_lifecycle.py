"""Google lifecycle fencing and per-capability sync evidence."""

import sqlalchemy as sa
from alembic import op

revision = "oss_0032"
down_revision = "oss_0031"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "google_lifecycle",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("epoch", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.Uuid()),
        sa.Column("sync_paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("imports_since", sa.DateTime(timezone=True)),
        sa.Column("gmail_last_success_at", sa.DateTime(timezone=True)),
        sa.Column("calendar_last_success_at", sa.DateTime(timezone=True)),
        sa.Column("gmail_attempt_generation", sa.Uuid()),
        sa.Column("calendar_attempt_generation", sa.Uuid()),
        sa.CheckConstraint("id = 1", name="single_google_lifecycle"),
    )
    op.execute(
        "INSERT INTO google_lifecycle (id, epoch, generation, imports_since) "
        "SELECT 1, gen_random_uuid(), CASE WHEN stored THEN gen_random_uuid() END, "
        "CASE WHEN stored THEN CURRENT_TIMESTAMP END FROM (SELECT EXISTS ("
        "SELECT 1 FROM google_connections WHERE refresh_token_sealed IS NOT NULL"
        ") AS stored) AS legacy"
    )


def downgrade():
    # The old runtime cannot enforce the pause. Persist both switches disabled so rolling
    # back cannot silently resume a saved or externally configured credential.
    op.execute(
        "UPDATE correspondence_sync_settings SET enabled = false, calendar_enabled = false "
        "WHERE EXISTS (SELECT 1 FROM google_lifecycle WHERE sync_paused)"
    )
    op.drop_table("google_lifecycle")
