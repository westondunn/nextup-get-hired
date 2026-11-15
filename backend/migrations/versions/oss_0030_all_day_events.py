"""All-day calendar events: record that an imported event has a date and no time.

An all-day event is stored with ``received_at`` at midnight UTC of its date. Without this
flag nothing distinguishes that from an event that really starts at midnight UTC, so the
date was shown shifted in any time zone west of UTC.
"""

import sqlalchemy as sa
from alembic import op

revision = "oss_0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade():
    # Existing rows become false. Events inside the sync window get the right value the
    # next time calendar sync reads them; nothing is inferred from the note text.
    op.add_column(
        "communications",
        sa.Column("all_day", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade():
    # The flag is read from the provider, not entered by the user, so nothing of the
    # user's is lost. The events themselves stay.
    op.drop_column("communications", "all_day")
