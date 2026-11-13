"""Add read-only Google Calendar sync settings and status columns."""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

TABLE = "correspondence_sync_settings"


def upgrade():
    op.add_column(
        TABLE, sa.Column("calendar_enabled", sa.Boolean(), nullable=False, server_default="false")
    )
    op.add_column(
        TABLE,
        sa.Column("calendar_lookahead_days", sa.Integer(), nullable=False, server_default="14"),
    )
    op.add_column(TABLE, sa.Column("calendar_last_run_at", sa.DateTime(timezone=True)))
    op.add_column(
        TABLE,
        sa.Column("calendar_last_status", sa.String(30), nullable=False, server_default="not_run"),
    )
    op.add_column(
        TABLE, sa.Column("calendar_last_error", sa.Text(), nullable=False, server_default="")
    )
    op.add_column(
        TABLE, sa.Column("calendar_last_imported", sa.Integer(), nullable=False, server_default="0")
    )
    op.create_check_constraint(
        "calendar_lookahead", TABLE, "calendar_lookahead_days BETWEEN 1 AND 60"
    )


def downgrade():
    op.drop_constraint("calendar_lookahead", TABLE, type_="check")
    for column in (
        "calendar_last_imported",
        "calendar_last_error",
        "calendar_last_status",
        "calendar_last_run_at",
        "calendar_lookahead_days",
        "calendar_enabled",
    ):
        op.drop_column(TABLE, column)
