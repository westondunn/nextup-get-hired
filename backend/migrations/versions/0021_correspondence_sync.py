"""Add read-only correspondence sync settings and provenance on communications."""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "communications",
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
    )
    op.add_column("communications", sa.Column("source_id", sa.String(200), nullable=True))
    op.add_column("communications", sa.Column("thread_id", sa.String(200), nullable=True))
    op.add_column("communications", sa.Column("sender", sa.String(320), nullable=True))
    op.add_column(
        "communications",
        sa.Column(
            "suggested_pursuit_id",
            sa.Uuid(),
            sa.ForeignKey("pursuits.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ux_communications_source_id",
        "communications",
        ["source", "source_id"],
        unique=True,
        postgresql_where=sa.text("source_id IS NOT NULL"),
    )
    op.create_table(
        "correspondence_sync_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("query", sa.String(500), nullable=False, server_default="label:job-search"),
        sa.Column("max_messages_per_run", sa.Integer(), nullable=False, server_default="25"),
        sa.Column("cursor_epoch", sa.BigInteger(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(30), nullable=False, server_default="not_run"),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("last_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("id=1", name="single_correspondence_sync_settings"),
        sa.CheckConstraint("max_messages_per_run BETWEEN 1 AND 200", name="correspondence_batch"),
    )


def downgrade():
    op.drop_table("correspondence_sync_settings")
    op.drop_index("ux_communications_source_id", table_name="communications")
    op.drop_column("communications", "suggested_pursuit_id")
    op.drop_column("communications", "sender")
    op.drop_column("communications", "thread_id")
    op.drop_column("communications", "source_id")
    op.drop_column("communications", "source")
