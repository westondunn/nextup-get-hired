"""Add evidence bank and resume versions tables."""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("seed_key", sa.String(20)),
        sa.Column("topic", sa.String(500), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "verification_status",
            sa.String(30),
            nullable=False,
            server_default="needs_user_confirmation",
        ),
        sa.Column("source", sa.String(300)),
        sa.Column("scope", sa.String(300)),
        sa.Column("dates", sa.String(100)),
        sa.Column("personal_contribution", sa.Text(), nullable=False, server_default=""),
        sa.Column("permitted_wording", sa.Text(), nullable=False, server_default=""),
        sa.Column("instruction", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "verification_status IN ('needs_user_confirmation','confirmed','rejected')",
            name="evidence_verification_status",
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_evidence_seed_key ON evidence (seed_key) WHERE seed_key IS NOT NULL"
    )
    op.create_table(
        "resume_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("variant_name", sa.String(120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("variant_name", "version_number", name="resume_variant_version"),
    )


def downgrade():
    op.drop_table("resume_versions")
    op.drop_table("evidence")
