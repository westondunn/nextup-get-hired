"""Nextup database guard.

Building blocks (Batch 2a, database-free): ``errors``, ``lineage``, ``facts``, ``policy``,
``plan``. Batch 2b adds ``marker`` (guard-owned tables, database ledger), the command
line (``python -m app.guard``) and the entry-point wiring in this module:

* ``check_runtime(dbapi_connection)``: read-only runtime identity check. Installed as the
  engine's ``first_connect`` hook (``install_runtime_guard``), and triggered before
  serving by the FastAPI lifespan, Celery ``worker_init``/``beat_init`` and
  ``guard exec`` (``check_service_startup``).
* ``apply_in_transaction``: the **only** path that may change the schema. One
  transaction: advisory lock, facts, decision, signature/expiry/binding check,
  ledger consume, marker (INIT), Alembic, privilege lock-down, post-check.
* ``plan_migration`` / ``apply_migration``: the one implementation of plan and apply. The
  CLI (``python -m app.guard plan-apply|apply``), ``migrate_programmatically`` (CI and test
  suites) and ``alembic -x nextup_token=stdin`` all end in ``apply_in_transaction``. There is
  no test-only, CI-only or environment-variable authorization. Command-line
  entry points take the token on standard input only; a token passed as an argument is
  refused (NXG-A10) and never consumed or echoed. Launchers use
  ``plan-apply``, so the token never leaves the guard process at all.
* ``run_alembic(context, metadata)``: called by ``migrations/env.py`` for every Alembic
  entry point (CLI, ``python -m alembic``, ``command.upgrade``). Writes require a
  single-use authorization issued in this process by ``apply_in_transaction``; everything
  else runs in a READ ONLY transaction and needs no token.

Heavy imports (SQLAlchemy, settings, Alembic) stay inside functions so the policy layer
remains importable on its own.
"""

import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from app.guard.errors import GuardError, GuardRefused, classify_connection_error

logger = logging.getLogger("nextup.guard")

# Transaction-level advisory lock key shared by every schema-changing path.
GUARD_LOCK_KEY = int.from_bytes(b"nxguard1", "big")
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
# Guard-owned tables: never part of the application models, so Alembic autogenerate
# (``alembic check``) must not report them as tables to remove.
GUARD_TABLES = frozenset({"nextup_environment", "nextup_migration_authorizations"})
_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_BIND = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")

_lineage = None


def _load_lineage():
    global _lineage
    if _lineage is None:
        from app.guard import lineage  # noqa: PLC0415

        _lineage = lineage.load()
    return _lineage


def _roles(identity) -> tuple[str, str]:
    from app.config import ENV_PREFIX  # noqa: PLC0415

    prefix = ENV_PREFIX[identity.environment]
    return f"{prefix}_owner", f"{prefix}_app"


def _facts_error(exc: BaseException) -> GuardError:
    """Driver failure while reading facts: classify without reading its text."""
    error = classify_connection_error(exc)
    return error if error.code != "NXG-C05" else GuardRefused("NXG-I09")


# ---------- query adapters (facts.gather / marker take ``query(sql, params)``) ----------


def dbapi_query(dbapi_connection):
    def query(sql, params):
        cursor = dbapi_connection.cursor()
        try:
            if params:
                cursor.execute(_BIND.sub(r"%(\1)s", sql), params)
            else:
                cursor.execute(sql)
            return cursor.fetchall() if cursor.description else []
        finally:
            cursor.close()

    return query


def sqlalchemy_query(connection):
    from sqlalchemy import text  # noqa: PLC0415

    def query(sql, params):
        result = connection.execute(text(sql), params or {})
        return result.fetchall() if result.returns_rows else []

    return query


# ---------- runtime (api, worker, scheduler) ----------


def read_facts_dbapi(dbapi_connection, identity):
    from app.guard.facts import READ_ONLY_PREAMBLE, gather  # noqa: PLC0415

    owner, app = _roles(identity)
    query = dbapi_query(dbapi_connection)
    dbapi_connection.rollback()
    try:
        for statement in READ_ONLY_PREAMBLE:
            query(statement, None)
        return gather(query, owner_role=owner, app_role=app)
    finally:
        dbapi_connection.rollback()


def check_runtime(dbapi_connection, settings=None):
    """PROCEED-RUNTIME or raise GuardRefused. Read-only; ends with ROLLBACK."""
    from app.config import get_settings  # noqa: PLC0415
    from app.guard.policy import decide_runtime  # noqa: PLC0415

    settings = settings or get_settings()
    identity = settings.identity
    try:
        facts = read_facts_dbapi(dbapi_connection, identity)
    except GuardError:
        raise
    except Exception as exc:  # noqa: BLE001 - driver text may carry host or user names
        raise _facts_error(exc) from None
    decision = decide_runtime(facts, identity, _load_lineage(), settings)
    logger.info("nextup-guard: PROCEED-RUNTIME (env=%s)", identity.environment)
    return decision


def install_runtime_guard(engine, settings=None) -> None:
    """Every runtime engine verifies the database identity on its first connection.
    ``settings`` defaults to the process settings; test suites pass an explicit runtime
    identity for their per-schema engines."""
    from sqlalchemy import event  # noqa: PLC0415

    def on_first_connect(dbapi_connection, _record):
        try:
            check_runtime(dbapi_connection, settings)
        except BaseException:
            try:
                dbapi_connection.close()
            except Exception:  # noqa: BLE001
                pass
            raise

    event.listen(engine, "first_connect", on_first_connect)


def check_service_startup() -> None:
    """Connect through the runtime engine so its guard hook runs before serving."""
    from sqlalchemy.exc import SQLAlchemyError  # noqa: PLC0415

    from app.db import get_engine  # noqa: PLC0415

    try:
        with get_engine().connect():
            pass
    except GuardError:
        raise
    except SQLAlchemyError as exc:
        raise classify_connection_error(exc) from None


def celery_startup_check(**_kwargs) -> None:
    """worker_init / beat_init handler: refuse before consuming or scheduling tasks."""
    try:
        check_service_startup()
    except GuardError as exc:
        logger.error(exc.line())
        print(exc.line(), file=sys.stderr, flush=True)
        raise SystemExit(exc.exit_code) from None


# ---------- in-process authorization registry ----------


@dataclass
class _Issued:
    authorization: object
    connection: object
    used: bool = False


# Authorizations verified by ``apply_in_transaction``, valid only for the duration of its
# Alembic call, on that one connection, once.
_ISSUED: dict[int, _Issued] = {}


def _register(authorization, connection) -> None:
    _ISSUED[id(authorization)] = _Issued(authorization, connection)


# ---------- schema changes ----------


def _post_check(query, decision, identity, settings, owner, app) -> None:
    from app.guard.facts import gather  # noqa: PLC0415

    after = gather(query, owner_role=owner, app_role=app)
    if after.alembic_versions != (decision.target,):
        raise GuardRefused("NXG-L03", env=identity.environment)
    if len(after.markers) != 1:
        raise GuardRefused("NXG-L05", env=identity.environment)
    if after.foreign_grantees and not settings.external_classifier_enabled:
        raise GuardRefused("NXG-R02", env=identity.environment)


def apply_in_transaction(connection, settings, token, *, operation, target, run, now=None):
    """The single schema-changing path. ``run(connection, authorization, decision)`` performs
    the Alembic command on ``connection``; any failure rolls back everything, including
    the ledger row and the marker."""
    from sqlalchemy.exc import SQLAlchemyError  # noqa: PLC0415

    identity = settings.identity
    if identity.role != "migrator":
        raise GuardRefused("NXG-A01", env=identity.environment)
    if connection.in_transaction():
        raise GuardRefused("NXG-A02", env=identity.environment)
    try:
        return _apply(
            connection, settings, token, operation=operation, target=target, run=run, now=now
        )
    except GuardError:
        raise
    except SQLAlchemyError:
        # Statement text and driver messages may include data; report a fixed code only.
        raise GuardRefused("NXG-A09", env=identity.environment) from None


def _apply(connection, settings, token, *, operation, target, run, now):
    from app.guard import marker  # noqa: PLC0415
    from app.guard.facts import gather  # noqa: PLC0415
    from app.guard.plan import GUARD_VERSION, revalidate_and_consume  # noqa: PLC0415
    from app.guard.policy import decide_migration  # noqa: PLC0415

    identity = settings.identity
    lineage = _load_lineage()
    owner, app = _roles(identity)
    now = int(time.time()) if now is None else int(now)
    query = sqlalchemy_query(connection)
    with connection.begin():
        query("SET LOCAL lock_timeout = '30s'", None)
        query("SELECT pg_advisory_xact_lock(:key)", {"key": GUARD_LOCK_KEY})
        facts = gather(query, owner_role=owner, app_role=app)
        pre = decide_migration(
            facts, identity, lineage, operation=operation, target=target, settings=settings
        )
        if not pre.changes_schema:
            raise GuardRefused("NXG-A02", env=identity.environment)
        if pre.mode == "INIT":
            marker.create_tables(query, app)
        ledger = marker.DatabaseLedger(query, operation=pre.mode, target=pre.target)
        decision, authorization = revalidate_and_consume(
            token,
            facts,
            identity,
            lineage,
            now=now,
            ledger=ledger,
            operation=operation,
            target=target,
            settings=settings,
        )
        if decision.mode == "INIT":
            marker.insert_marker(query, identity, facts, GUARD_VERSION)
        _register(authorization, connection)
        try:
            run(connection, authorization, decision)
        finally:
            _ISSUED.pop(id(authorization), None)
        marker.lock_down(query, app)
        _post_check(query, decision, identity, settings, owner, app)
    logger.info(
        "nextup-guard: APPLIED %s to %s (env=%s)",
        decision.mode,
        decision.target,
        identity.environment,
    )
    return decision


def require_migrator(settings):
    if settings.identity.role != "migrator":
        raise GuardRefused("NXG-I04", env=settings.identity.environment)
    return settings


def read_facts(connection, identity):
    """Read-only facts on a SQLAlchemy connection (READ ONLY transaction, rolled back)."""
    from app.guard.facts import READ_ONLY_PREAMBLE, gather  # noqa: PLC0415

    owner, app = _roles(identity)
    transaction = connection.begin()
    try:
        query = sqlalchemy_query(connection)
        for statement in READ_ONLY_PREAMBLE:
            query(statement, None)
        return gather(query, owner_role=owner, app_role=app)
    except GuardError:
        raise
    except Exception as exc:  # noqa: BLE001 - driver text may carry host or user names
        raise _facts_error(exc) from None
    finally:
        transaction.rollback()


def run_alembic_command(connection, authorization, decision) -> None:
    """The Alembic step inside ``apply_in_transaction``: same connection, same transaction."""
    from alembic import command  # noqa: PLC0415
    from alembic.config import Config  # noqa: PLC0415

    config = Config(str(ALEMBIC_INI))
    config.attributes["connection"] = connection
    config.attributes["nextup_authorization"] = authorization
    if decision.mode == "DOWNGRADE":
        command.downgrade(config, decision.target)
    else:
        command.upgrade(config, decision.target)


def plan_migration(engine, settings, *, operation="upgrade", target=None, ttl=None, now=None):
    """Read-only. Returns ``(decision, token)``; the token is ``None`` for NOOP."""
    from app.guard.plan import DEFAULT_TTL_SECONDS, plan  # noqa: PLC0415

    require_migrator(settings)
    identity = settings.identity
    with engine.connect() as connection:
        facts = read_facts(connection, identity)
    return plan(
        facts,
        identity,
        _load_lineage(),
        now=int(time.time()) if now is None else int(now),
        operation=operation,
        target=target,
        settings=settings,
        ttl=DEFAULT_TTL_SECONDS if ttl is None else ttl,
    )


def apply_migration(engine, settings, token, *, operation="upgrade", target=None, now=None):
    """Apply a token from ``plan_migration``. Downgrades need an explicit target."""
    require_migrator(settings)
    if target is None:
        if operation != "upgrade":
            raise GuardRefused("NXG-A06", env=settings.identity.environment)
        target = _load_lineage().head
    with engine.connect() as connection:
        return apply_in_transaction(
            connection,
            settings,
            token,
            operation=operation,
            target=target,
            run=run_alembic_command,
            now=now,
        )


def migrate_programmatically(engine, settings, *, operation="upgrade", target=None, ttl=60):
    """Plan, then apply that plan's token: the CLI's two steps without the human prompt.

    No broader than the CLI: it needs the migrator identity and its migration key, issues
    a fresh nonce bound to the current state, and applies only through
    ``apply_in_transaction`` (lock, revalidation, ledger, one-time use). Intended for
    disposable CI and test databases, where nobody types a confirmation code.
    """
    decision, token = plan_migration(engine, settings, operation=operation, target=target, ttl=ttl)
    if token is None:
        return decision
    return apply_migration(engine, settings, token, operation=operation, target=decision.target)


# ---------- Alembic (migrations/env.py) ----------

_OPERATION_FUNCTIONS = {"upgrade": "upgrade", "downgrade": "downgrade", "do_stamp": "stamp"}


def _operation(opts) -> str | None:
    fn = opts.get("fn")
    return _OPERATION_FUNCTIONS.get(getattr(fn, "__name__", ""))


def _target(opts, lineage) -> str:
    destination = opts.get("destination_rev")
    if isinstance(destination, (tuple, list)):
        destination = destination[0] if len(destination) == 1 else None
    if destination in ("head", "heads"):
        return lineage.head
    return str(destination)


def _include_name(name, type_, _parent_names) -> bool:
    return not (type_ == "table" and name in GUARD_TABLES)


def _configure_and_run(context, connection, target_metadata) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, include_name=_include_name
    )
    with context.begin_transaction():  # external transaction: Alembic adds none of its own
        context.run_migrations()


def _read_only(context, connection, target_metadata) -> None:
    if connection.in_transaction():
        raise GuardRefused("NXG-A01")
    transaction = connection.begin()
    try:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        connection.exec_driver_sql("SET LOCAL statement_timeout = '60s'")
        _configure_and_run(context, connection, target_metadata)
    finally:
        transaction.rollback()


def _check_programmatic(authorization, connection, operation, opts) -> None:
    entry = _ISSUED.get(id(authorization)) if authorization is not None else None
    if entry is None or entry.authorization is not authorization:
        raise GuardRefused("NXG-A01")
    if entry.connection is not connection:
        raise GuardRefused("NXG-A02")
    if entry.used:
        raise GuardRefused("NXG-A03")
    entry.used = True
    expected = "downgrade" if authorization.operation == "DOWNGRADE" else "upgrade"
    if operation != expected or _target(opts, _load_lineage()) != authorization.target:
        raise GuardRefused("NXG-A02")


def migration_engine(settings, *, schema=None):
    """Engine for plan/apply and env.py: no runtime hook, no pooling, no URL string.
    ``schema`` sets the search path (isolated test schemas); identity checks still apply."""
    from sqlalchemy import create_engine  # noqa: PLC0415
    from sqlalchemy.pool import NullPool  # noqa: PLC0415

    from app.config import refuse_client_environment  # noqa: PLC0415

    refuse_client_environment()  # libpq would read PG* for every parameter not passed here
    connect_args = {"connect_timeout": 5}
    if schema is not None:
        if not _SCHEMA_NAME.fullmatch(schema):
            raise GuardRefused("NXG-I02", env=settings.identity.environment)
        connect_args["options"] = f"-csearch_path={schema}"
    return create_engine(settings.database_url, poolclass=NullPool, connect_args=connect_args)


def run_alembic(context, target_metadata, environ=None) -> None:
    """Every Alembic entry point passes here. No environment variable enables writes."""
    from sqlalchemy.exc import SQLAlchemyError  # noqa: PLC0415

    from app.config import get_settings  # noqa: PLC0415

    environ = os.environ if environ is None else environ
    environment_context = getattr(context, "_proxy", None)
    opts = getattr(environment_context, "context_opts", None)
    if not isinstance(opts, dict):
        raise GuardRefused("NXG-A01")  # unknown Alembic internals: fail closed

    if context.is_offline_mode():
        if environ.get("NEXTUP_ALEMBIC_OFFLINE_REVIEW") != "1":
            raise GuardRefused("NXG-A08")
        # Dialect-only URL: never connects, reads no settings and no secrets.
        context.configure(
            url="postgresql+psycopg://",
            target_metadata=target_metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
            include_name=_include_name,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    write = "destination_rev" in opts  # upgrade, downgrade and stamp
    operation = _operation(opts) if write else None
    if write and operation is None:
        raise GuardRefused("NXG-A06")
    attributes = context.config.attributes
    connection = attributes.get("connection")
    if connection is not None:
        authorization = attributes.get("nextup_authorization")
        if write:
            _check_programmatic(authorization, connection, operation, opts)
            _configure_and_run(context, connection, target_metadata)
        else:
            # Read-only commands never need (or consume) an authorization.
            _read_only(context, connection, target_metadata)
        return

    settings = get_settings()
    xargs = context.get_x_argument(as_dictionary=True)
    unknown = set(xargs) - {"nextup_token"}
    if unknown:
        raise GuardRefused("NXG-A05", env=settings.identity.environment)
    supplied = xargs.get("nextup_token")
    if supplied and supplied != "stdin":
        # A literal token on the command line: refused, never used.
        raise GuardRefused("NXG-A10", env=settings.identity.environment)
    if write and not supplied:
        # Refused before any connection is attempted.
        raise GuardRefused("NXG-A01", env=settings.identity.environment)
    token = None
    if write:
        from app.guard.__main__ import read_token  # noqa: PLC0415

        token = read_token()
    engine = migration_engine(settings)
    try:
        with engine.connect() as connection:
            if not write:
                _read_only(context, connection, target_metadata)
            else:
                apply_in_transaction(
                    connection,
                    settings,
                    token,
                    operation=operation,
                    target=_target(opts, _load_lineage()),
                    run=lambda conn, _auth, _decision: _configure_and_run(
                        context, conn, target_metadata
                    ),
                )
    except GuardError:
        raise
    except SQLAlchemyError as exc:
        raise classify_connection_error(exc) from None
    finally:
        engine.dispose()
