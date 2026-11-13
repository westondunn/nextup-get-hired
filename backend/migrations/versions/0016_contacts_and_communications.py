"""Add contacts and communications tables."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "contacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("company", sa.String(200)),
        sa.Column("title", sa.String(200)),
        sa.Column("email", sa.String(320)),
        sa.Column("phone", sa.String(40)),
        sa.Column("linkedin_url", sa.String(500)),
        sa.Column("relationship", sa.String(40), nullable=False, server_default="unknown"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("do_not_contact", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("introduced_by", sa.String(200)),
        sa.Column("last_contacted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "relationship IN ('unknown','recruiter','hiring_manager','referral','colleague',"
            "'mentor','friend','other')",
            name="contact_relationship",
        ),
    )
    op.create_table(
        "communications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("contact_id", sa.Uuid(), sa.ForeignKey("contacts.id", ondelete="SET NULL")),
        sa.Column("pursuit_id", sa.Uuid(), sa.ForeignKey("pursuits.id", ondelete="SET NULL")),
        sa.Column(
            "campaign_task_id",
            sa.Uuid(),
            sa.ForeignKey("campaign_tasks.id", ondelete="SET NULL"),
        ),
        sa.Column("channel", sa.String(30), nullable=False, server_default="email"),
        sa.Column("direction", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("subject", sa.String(500), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "channel IN ('email','linkedin','phone','in_person','other')",
            name="comm_channel",
        ),
        sa.CheckConstraint(
            "direction IN ('outbound','inbound','note')",
            name="comm_direction",
        ),
        sa.CheckConstraint(
            "status IN ('draft','copied','sent','received','private_note')",
            name="comm_status",
        ),
    )
    op.create_index("ix_communications_contact_id", "communications", ["contact_id"])
    op.create_index("ix_communications_pursuit_id", "communications", ["pursuit_id"])

    # Follow-up rules table
    op.create_table(
        "follow_up_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("rule_key", sa.String(60), nullable=False),
        sa.Column("trigger", sa.String(80), nullable=False),
        sa.Column("delay_business_days", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("action", sa.String(40), nullable=False, server_default="create_review_task"),
        sa.Column(
            "contact_required_for_outreach",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("config", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("rule_key", name="follow_up_rule_key_unique"),
    )


def downgrade():
    op.drop_table("follow_up_rules")
    op.drop_table("communications")
    op.drop_table("contacts")
