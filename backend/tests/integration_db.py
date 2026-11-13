"""Disposable integration-test databases through the database guard.

Runs only in the CI ``tests`` service (``NEXTUP_ENV=test``, migrator identity: owner
credential plus migration key, all as ``*_FILE``). There is no test-only authorization:

* schemas (``nextup_test_<32 hex>``, ``nextup_jobs_test_<32 hex>``) and databases
  (``nextup_migration_test_<32 hex>``) are created by the owner role;
* every schema change goes through ``app.guard.migrate_programmatically``, i.e. a read-only
  plan and then ``apply_in_transaction`` with that plan's single-use token, exactly like
  ``python -m app.guard plan`` / ``apply``;
* code under test gets **runtime** (``_app``) engines with the runtime guard installed, so
  each per-schema engine proves identity, marker and privileges before use;
* subprocesses (workers, an isolated API) receive the runtime identity with a password
  *file path*; no password or URL is ever placed in an argument or environment value.
"""

import os
import re
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app import guard
from app.config import ENV_PREFIX, get_settings, load_settings

# The CI tests service mounts the runtime password here (compose.ci.yaml).
APP_PASSWORD_FILE = "/run/secrets/db_app_password"
TEST_SCHEMA = re.compile(r"^nextup_(jobs_)?test_[0-9a-f]{32}$")
TEST_DATABASE = re.compile(r"^nextup_migration_test_[0-9a-f]{32}$")
PROVISIONING_SETTING = "complete-v1"
MIGRATOR_ONLY = ("NEXTUP_DB_ROLE", "NEXTUP_MIGRATION_KEY", "NEXTUP_MIGRATION_KEY_FILE")
_SCHEMAS: dict[int, str] = {}


def migrator_settings(**overrides):
    settings = load_settings({**os.environ, **overrides})
    identity = settings.identity
    if (identity.environment, identity.role) != ("test", "migrator"):
        raise RuntimeError("Integration databases need the CI tests service (test migrator)")
    return settings


def runtime_environment(**overrides) -> dict[str, str]:
    """The runtime identity for subprocesses: same database, `_app` role, password file."""
    env = {k: v for k, v in os.environ.items() if k not in MIGRATOR_ONLY}
    prefix = ENV_PREFIX[env.get("NEXTUP_ENV", "test")]
    env.update(NEXTUP_DB_USER=f"{prefix}_app", NEXTUP_DB_PASSWORD_FILE=APP_PASSWORD_FILE)
    env.update(overrides)
    return env


def runtime_settings(**overrides):
    settings = load_settings(runtime_environment(**overrides))
    if settings.identity.role != "runtime":
        raise RuntimeError("Runtime settings must not carry the migrator role")
    return settings


def stack_engine():
    """Runtime-role engine on the running CI stack's own database (marker env ``ci``)."""
    return runtime_engine("public", runtime_settings(NEXTUP_ENV="ci"))


def owner_engine(schema=None, settings=None):
    return guard.migration_engine(settings or migrator_settings(), schema=schema)


def runtime_engine(schema, settings=None, **engine_options):
    """App-role engine for code under test; the runtime guard checks it on first connect."""
    settings = settings or runtime_settings()
    engine = create_engine(
        settings.database_url,
        connect_args={"options": f"-csearch_path={schema}", "connect_timeout": 3},
        **engine_options,
    )
    guard.install_runtime_guard(engine, settings)
    _SCHEMAS[id(engine)] = schema
    return engine


def _checked_schema(schema):
    if not TEST_SCHEMA.fullmatch(schema):
        raise RuntimeError("Refusing to touch a schema that is not a generated test schema")
    return schema


def create_schema(prefix="nextup_test") -> str:
    """Owner creates the schema and grants the app role only what runtime DML needs."""
    schema = _checked_schema(f"{prefix}_{uuid4().hex}")
    settings = migrator_settings()
    app = f"{ENV_PREFIX[settings.identity.environment]}_app"
    owner = settings.identity.database.user
    engine = owner_engine(settings=settings)
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{app}"'))
            for grant in (
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES",
                "GRANT USAGE, SELECT ON SEQUENCES",
                "GRANT EXECUTE ON FUNCTIONS",
            ):
                connection.execute(
                    text(
                        f'ALTER DEFAULT PRIVILEGES FOR ROLE "{owner}" IN SCHEMA "{schema}" '
                        f'{grant} TO "{app}"'
                    )
                )
    finally:
        engine.dispose()
    return schema


def drop_schema(schema) -> None:
    engine = owner_engine()
    try:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{_checked_schema(schema)}" CASCADE'))
    finally:
        engine.dispose()


def migrate_schema(schema, *, operation="upgrade", target=None, settings=None):
    """Plan + apply (single-use token) for one test schema; downgrades need a target."""
    settings = settings or migrator_settings()
    engine = owner_engine(_checked_schema(schema), settings)
    try:
        return guard.migrate_programmatically(engine, settings, operation=operation, target=target)
    finally:
        engine.dispose()


def migrate_engine_schema(engine, **kwargs):
    """Same, for the schema behind a runtime engine created by ``runtime_engine``."""
    return migrate_schema(_SCHEMAS[id(engine)], **kwargs)


def owner_engine_for(engine):
    """Owner engine on the same schema (writes while the schema is at an older revision)."""
    return owner_engine(_SCHEMAS[id(engine)])


def schema_runtime_environment(schema, **extra) -> dict[str, str]:
    """Environment for a worker/API subprocess bound to one test schema."""
    return runtime_environment(NEXTUP_TEST_SCHEMA=_checked_schema(schema), **extra)


# Subprocess prelude: redirect the runtime engine to the test schema, with the guard.
SUBPROCESS_ENGINE = """
import os, sqlalchemy
import app.db
from app import guard
from app.config import get_settings
_settings = get_settings()
engine = sqlalchemy.create_engine(_settings.database_url,
    connect_args={'options': '-csearch_path=' + os.environ['NEXTUP_TEST_SCHEMA']})
guard.install_runtime_guard(engine, _settings)
app.db.get_engine = lambda: engine
"""


# ---------- disposable migration databases (test_migrations_integration) ----------


def create_database():
    """Owner (CREATEDB in CI only) creates a database from template1, which the CI
    first-boot script prepared with pg_trgm and the system-identifier grant. The owner
    then records provisioning as complete for this disposable database."""
    settings = migrator_settings()
    name = f"nextup_migration_test_{uuid4().hex}"
    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        with admin.connect() as connection:
            can_create = connection.scalar(
                text("SELECT rolcreatedb FROM pg_roles WHERE rolname=current_user")
            )
            assert can_create, "Migration tests need CREATEDB; use the standalone CI stack."
            connection.execute(text(f'CREATE DATABASE "{name}" TEMPLATE template1'))
            connection.execute(
                text(
                    f"ALTER DATABASE \"{name}\" SET nextup.provisioning = '{PROVISIONING_SETTING}'"
                )
            )
    finally:
        admin.dispose()
    return name


def database_settings(name):
    if not TEST_DATABASE.fullmatch(name):
        raise RuntimeError("Refusing a database that is not a generated migration test database")
    return migrator_settings(NEXTUP_DB_NAME=name)


def drop_database(name):
    if not TEST_DATABASE.fullmatch(name):
        raise RuntimeError("Refusing to drop a database that is not a generated test database")
    admin = create_engine(
        get_settings().database_url, isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    try:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}"'))
    finally:
        admin.dispose()


def plan_token(name, *, operation="upgrade", target=None):
    """Read-only plan for a migration test database; returns (decision, token)."""
    settings = database_settings(name)
    engine = guard.migration_engine(settings)
    try:
        return guard.plan_migration(engine, settings, operation=operation, target=target)
    finally:
        engine.dispose()
