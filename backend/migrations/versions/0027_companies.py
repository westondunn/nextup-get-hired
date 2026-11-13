"""Canonical companies, linked from pursuits and contacts.

The external n8n "Job Search Email Labeler" queries ``companies`` directly, so its
columns are a contract: id, name, name_normalized, aliases, domains, status.

``name_normalized`` is a generated column computed by ``nextup_normalize_company``,
which this revision creates; the application mirrors it in ``app.companies``.
The backfill is idempotent and deterministic (ids derive from the normalized name,
timestamps from the oldest source row) so a downgrade and re-upgrade reproduce it.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

STATUSES = "'tracking','applied','interviewing','contact_only','archived'"
# Adzuna's stand-in for a missing employer; never a company.
PLACEHOLDERS = "'company not provided'"

# lower → drop apostrophes and full stops (J.P. → jp, O'Neil → oneil) → every other
# non-alphanumeric becomes a space → collapse spaces → strip a leading "the" and any
# run of trailing corporate suffixes. Stripping never empties the name.
NORMALIZE_FUNCTION = r"""
CREATE OR REPLACE FUNCTION nextup_normalize_company(value text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE
RETURN (
    WITH cleaned AS (
        SELECT btrim(regexp_replace(regexp_replace(regexp_replace(
            lower(coalesce(value, '')),
            '[''’.]', '', 'g'),
            '[^[:alnum:][:space:]]', ' ', 'g'),
            '[[:space:]]+', ' ', 'g')) AS v
    ), stripped AS (
        SELECT v, btrim(regexp_replace(
            regexp_replace(v, '^the ', ''),
            '( (inc|llc|corp|corporation|co|ltd|plc))+$', '')) AS s
        FROM cleaned
    )
    SELECT CASE WHEN s = '' THEN v ELSE s END FROM stripped
)
"""

BACKFILL = f"""
WITH names AS (
    SELECT btrim(job->>'company') AS name, 'pursuit' AS src, created_at
    FROM pursuits WHERE coalesce(btrim(job->>'company'), '') <> ''
    UNION ALL
    SELECT btrim(company), 'contact', created_at
    FROM contacts WHERE coalesce(btrim(company), '') <> ''
), spelled AS (
    SELECT nextup_normalize_company(name) AS norm, name, count(*) AS uses,
           bool_or(src = 'pursuit') AS from_pursuit, min(created_at) AS first_seen
    FROM names GROUP BY 1, 2
), ranked AS (
    SELECT *, row_number() OVER (
        PARTITION BY norm ORDER BY uses DESC, from_pursuit DESC, length(name) DESC, name
    ) AS rank
    FROM spelled
    WHERE norm <> '' AND norm NOT IN ({PLACEHOLDERS})
)
INSERT INTO companies (id, name, aliases, created_at, updated_at)
SELECT md5('company:' || chosen.norm)::uuid,
       chosen.name,
       -- Other spellings that collapsed into this company stay findable as aliases.
       coalesce((
           SELECT array_agg(other.name ORDER BY other.name)
           FROM (
               SELECT DISTINCT ON (lower(r.name)) r.name
               FROM ranked r
               WHERE r.norm = chosen.norm AND lower(r.name) <> lower(chosen.name)
               ORDER BY lower(r.name), r.name
           ) other
       ), '{{}}'),
       (SELECT min(first_seen) FROM ranked r WHERE r.norm = chosen.norm),
       (SELECT min(first_seen) FROM ranked r WHERE r.norm = chosen.norm)
FROM ranked chosen
WHERE chosen.rank = 1
ON CONFLICT (name_normalized) DO NOTHING
"""

LINK = """
UPDATE pursuits p SET company_id = c.id
FROM companies c
WHERE p.company_id IS NULL AND coalesce(btrim(p.job->>'company'), '') <> ''
  AND c.name_normalized = nextup_normalize_company(p.job->>'company');
UPDATE contacts k SET company_id = c.id
FROM companies c
WHERE k.company_id IS NULL AND coalesce(btrim(k.company), '') <> ''
  AND c.name_normalized = nextup_normalize_company(k.company);
"""

# Same rule as app.companies.refresh_status; a status the user chose is kept.
STATUS = """
UPDATE companies c SET status = CASE
    WHEN EXISTS (SELECT 1 FROM pursuits p WHERE p.company_id = c.id AND p.applied_at IS NOT NULL)
        THEN 'applied'
    WHEN NOT EXISTS (SELECT 1 FROM pursuits p WHERE p.company_id = c.id)
         AND EXISTS (SELECT 1 FROM contacts k WHERE k.company_id = c.id)
        THEN 'contact_only'
    ELSE 'tracking'
END
WHERE c.status NOT IN ('interviewing', 'archived')
"""


def upgrade():
    # Pinned to public: integration tests migrate throwaway schemas in the same
    # database, and an extension created inside one would vanish with it.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public")
    trgm_schema = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT n.nspname FROM pg_extension e "
                "JOIN pg_namespace n ON n.oid = e.extnamespace WHERE e.extname = 'pg_trgm'"
            )
        )
        .scalar_one()
    )
    op.execute(NORMALIZE_FUNCTION)
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "name_normalized",
            sa.Text(),
            sa.Computed("nextup_normalize_company(name)", persisted=True),
            nullable=False,
        ),
        sa.Column(
            "aliases",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "domains",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="tracking"),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(f"status IN ({STATUSES})", name="company_status"),
    )
    op.create_index("ux_companies_name_normalized", "companies", ["name_normalized"], unique=True)
    op.create_index("ix_companies_aliases", "companies", ["aliases"], postgresql_using="gin")
    op.create_index("ix_companies_domains", "companies", ["domains"], postgresql_using="gin")
    # The operator class is qualified so the index works whatever the search_path.
    op.execute(
        "CREATE INDEX ix_companies_name_normalized_trgm ON companies "
        f'USING gin (name_normalized "{trgm_schema}".gin_trgm_ops)'
    )
    for table in ("pursuits", "contacts"):
        op.add_column(
            table,
            sa.Column(
                "company_id",
                sa.Uuid(),
                sa.ForeignKey("companies.id", ondelete="SET NULL", name=f"{table}_company_id_fkey"),
            ),
        )
        op.create_index(f"ix_{table}_company_id", table, ["company_id"])
    op.execute(BACKFILL)
    op.execute(LINK)
    op.execute(STATUS)


def downgrade():
    # The free-text company fields were never changed, so nothing is lost but the links.
    for table in ("contacts", "pursuits"):
        op.drop_index(f"ix_{table}_company_id", table_name=table)
        op.drop_column(table, "company_id")
    op.drop_table("companies")
    op.execute("DROP FUNCTION IF EXISTS nextup_normalize_company(text)")
    # pg_trgm stays: it may predate this revision and other objects may use it.
