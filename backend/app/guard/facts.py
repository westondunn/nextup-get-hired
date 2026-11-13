"""Read-only facts about the connected database.

Every statement here is a SELECT over catalog views, ``alembic_version`` or the marker
table. Batch 2b runs them inside ``READ_ONLY_PREAMBLE`` (a READ ONLY transaction with
timeouts) and always ends with ROLLBACK. ``gather`` takes a ``query(sql, params)``
callable returning rows, so it is testable without a database.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

READ_ONLY_PREAMBLE = (
    "SET TRANSACTION READ ONLY",
    "SET LOCAL statement_timeout = '5s'",
    "SET LOCAL lock_timeout = '2s'",
)
MARKER_TABLE = "nextup_environment"
LEDGER_TABLE = "nextup_migration_authorizations"
CLASSIFIER_ROLE = "n8n"

_SCHEMA = "(current_schemas(false))[1]"

IDENTITY = (
    "SELECT current_database(), current_setting('cluster_name'), current_user::text, "
    f"session_user::text, current_setting('server_version_num')::int, {_SCHEMA}"
)
ROLE_ATTRIBUTES = (
    "SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls, rolreplication "
    "FROM pg_roles WHERE rolname = current_user"
)
CREATE_RIGHTS = (
    f"SELECT has_database_privilege(current_database(), 'CREATE'), "
    f"has_schema_privilege({_SCHEMA}, 'CREATE'), "
    "EXISTS (SELECT 1 FROM pg_roles o WHERE o.rolname = :owner "
    "AND o.rolname <> current_user AND pg_has_role(current_user, o.oid, 'MEMBER'))"
)
APPLICATION_TABLES = (
    "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    f"WHERE n.nspname = {_SCHEMA} AND c.relkind IN ('r', 'p') "
    f"AND c.relname NOT IN ('alembic_version', '{MARKER_TABLE}', '{LEDGER_TABLE}')"
)
TABLE_PRESENT = (
    "SELECT to_regclass(quote_ident((current_schemas(false))[1]) || '.' || quote_ident(:table)) "
    "IS NOT NULL"
)
ALEMBIC_ROWS = "SELECT version_num FROM alembic_version ORDER BY version_num"
MARKER_ROWS = (
    "SELECT environment, lineage, database_name, cluster_name, system_identifier, "
    f"instance_id::text, guard_version FROM {MARKER_TABLE}"
)
EXTENSION = "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')"
CLASSIFIER = "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"
FOREIGN_GRANTEES = (
    "SELECT DISTINCT coalesce(r.rolname, 'PUBLIC') FROM pg_class c "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "CROSS JOIN LATERAL aclexplode(c.relacl) a "
    "LEFT JOIN pg_roles r ON r.oid = a.grantee "
    f"WHERE n.nspname = {_SCHEMA} AND c.relkind IN ('r', 'p', 'v', 'm', 'S') "
    "AND coalesce(r.rolname, 'PUBLIC') NOT IN (:owner, :app) ORDER BY 1"
)
# Can the connected role change the guard's own state? (alembic_version, marker, ledger)
GUARD_TABLE_WRITES = (
    "SELECT coalesce(bool_or(has_table_privilege(c.oid, p.priv)), false) FROM pg_class c "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "CROSS JOIN (VALUES ('INSERT'), ('UPDATE'), ('DELETE'), ('TRUNCATE')) AS p(priv) "
    f"WHERE n.nspname = {_SCHEMA} "
    f"AND c.relname IN ('alembic_version', '{MARKER_TABLE}', '{LEDGER_TABLE}')"
)
# Provisioning sentinel. The first-boot script's final statement stores it for the
# database (ALTER DATABASE ... SET), which PostgreSQL records in pg_db_role_setting.
#
# The *effective* value alone proves nothing: any connected role can change
# it for its own session with SET or set_config(), and a client can supply it through libpq
# options. Provisioning is therefore established only by the persistent, database-wide
# catalog entry of the connected database; the effective value must then agree with it.
# Limit: a role that may alter the database's settings (a superuser, or the database owner
# once granted SET on this parameter, as the CI owner is) can write the persistent entry.
# The sentinel detects interrupted provisioning; it is not a defence against such a role.
PROVISIONING_KEY = "nextup.provisioning"
PROVISIONING = "SELECT current_setting('nextup.provisioning', true)"
PROVISIONED = "complete-v1"
# Every stored setting of the sentinel that could apply to this connection, with its scope:
#   database           this database, all roles (setrole = 0): the only accepted evidence
#   role-in-database   this database, one role
#   role               one role, every database (setdatabase = 0)
#   cluster            every role, every database (setdatabase = 0 and setrole = 0)
# Settings of other databases are not selected: the row must carry this database's OID.
PROVISIONING_PERSISTED = (
    "SELECT CASE WHEN s.setdatabase <> 0 AND s.setrole = 0 THEN 'database' "
    "WHEN s.setdatabase <> 0 THEN 'role-in-database' "
    "WHEN s.setrole <> 0 THEN 'role' ELSE 'cluster' END, cfg "
    "FROM pg_catalog.pg_db_role_setting s CROSS JOIN LATERAL unnest(s.setconfig) AS cfg "
    "WHERE (s.setdatabase = 0 OR s.setdatabase = "
    "(SELECT d.oid FROM pg_catalog.pg_database d WHERE d.datname = current_database())) "
    "AND lower(split_part(cfg, '=', 1)) = 'nextup.provisioning' ORDER BY 1, 2"
)
# Last: needs EXECUTE on pg_control_system(), granted by the bootstrap script (2b).
SYSTEM_IDENTIFIER = "SELECT system_identifier::text FROM pg_control_system()"

STATEMENTS = (
    IDENTITY,
    ROLE_ATTRIBUTES,
    CREATE_RIGHTS,
    APPLICATION_TABLES,
    TABLE_PRESENT,
    ALEMBIC_ROWS,
    MARKER_ROWS,
    EXTENSION,
    CLASSIFIER,
    FOREIGN_GRANTEES,
    GUARD_TABLE_WRITES,
    PROVISIONING,
    PROVISIONING_PERSISTED,
    SYSTEM_IDENTIFIER,
)

Query = Callable[[str, dict | None], Sequence[Sequence]]


@dataclass(frozen=True)
class Marker:
    environment: str
    lineage: str
    database_name: str
    cluster_name: str
    system_identifier: str
    instance_id: str | None
    guard_version: str


@dataclass(frozen=True)
class Facts:
    database: str
    cluster_name: str
    current_user: str
    session_user: str
    server_version_num: int
    schema: str
    superuser: bool
    createrole: bool
    createdb: bool
    bypassrls: bool
    replication: bool
    can_create_in_database: bool
    can_create_in_schema: bool
    member_of_owner: bool
    application_tables: int
    alembic_present: bool
    alembic_versions: tuple[str, ...]
    marker_present: bool
    markers: tuple[Marker, ...]
    pg_trgm: bool
    classifier_role_exists: bool
    foreign_grantees: tuple[str, ...]
    system_identifier: str | None
    # 2b: may the connected role write alembic_version, the marker or the ledger?
    guard_tables_writable: bool = True
    # 2c-A: effective value of nextup.provisioning in this session. Never sufficient alone.
    provisioning: str | None = None
    # Stored settings of the sentinel as (scope, "name=value"); None when the
    # catalog could not be read. See provisioning_verified().
    provisioning_persisted: tuple[tuple[str, str], ...] | None = None


def provisioning_verified(facts: "Facts") -> bool:
    """True only when the connected database carries exactly one stored, database-wide
    sentinel entry with the expected value, no stored entry in any other scope, and the
    effective value agrees. Unreadable catalog, missing, duplicate, differently spelled,
    role-scoped or cluster-wide entries and a diverging effective value all mean False."""
    entries = facts.provisioning_persisted
    if entries is None or len(entries) != 1:
        return False
    scope, entry = entries[0]
    if scope != "database" or entry != f"{PROVISIONING_KEY}={PROVISIONED}":
        return False
    return facts.provisioning == PROVISIONED


def gather(query: Query, *, owner_role: str, app_role: str) -> Facts:
    def one(sql, params=None):
        rows = query(sql, params)
        return tuple(rows[0]) if rows else ()

    database, cluster, user, session, version, schema = one(IDENTITY)
    attrs = one(ROLE_ATTRIBUTES) or (True, True, True, True, True)  # unknown role: worst case
    create_db, create_schema, member = one(CREATE_RIGHTS, {"owner": owner_role})
    (tables,) = one(APPLICATION_TABLES)
    (alembic_present,) = one(TABLE_PRESENT, {"table": "alembic_version"})
    versions = tuple(r[0] for r in query(ALEMBIC_ROWS, None)) if alembic_present else ()
    (marker_present,) = one(TABLE_PRESENT, {"table": MARKER_TABLE})
    markers = (
        tuple(
            Marker(*(None if v is None else str(v) for v in row))
            for row in query(MARKER_ROWS, None)
        )
        if marker_present
        else ()
    )
    (trgm,) = one(EXTENSION)
    (classifier,) = one(CLASSIFIER, {"role": CLASSIFIER_ROLE})
    grantees = tuple(r[0] for r in query(FOREIGN_GRANTEES, {"owner": owner_role, "app": app_role}))
    (guard_writable,) = one(GUARD_TABLE_WRITES) or (True,)  # no row: assume the worst
    (provisioning,) = one(PROVISIONING) or (None,)
    try:
        persisted = tuple((str(r[0]), str(r[1])) for r in query(PROVISIONING_PERSISTED, None))
    except Exception:  # noqa: BLE001 - unreadable catalog: provisioning is not established
        persisted = None
    try:
        system_identifier = one(SYSTEM_IDENTIFIER)[0]
    except Exception:  # noqa: BLE001 - permission denied or unsupported: treated as unavailable
        system_identifier = None
    return Facts(
        database=str(database),
        cluster_name=str(cluster),
        current_user=str(user),
        session_user=str(session),
        server_version_num=int(version),
        schema=str(schema),
        superuser=bool(attrs[0]),
        createrole=bool(attrs[1]),
        createdb=bool(attrs[2]),
        bypassrls=bool(attrs[3]),
        replication=bool(attrs[4]),
        can_create_in_database=bool(create_db),
        can_create_in_schema=bool(create_schema),
        member_of_owner=bool(member),
        application_tables=int(tables),
        alembic_present=bool(alembic_present),
        alembic_versions=versions,
        marker_present=bool(marker_present),
        markers=markers,
        pg_trgm=bool(trgm),
        classifier_role_exists=bool(classifier),
        foreign_grantees=grantees,
        system_identifier=None if system_identifier is None else str(system_identifier),
        guard_tables_writable=bool(guard_writable),
        provisioning=None if provisioning is None else str(provisioning),
        provisioning_persisted=persisted,
    )
