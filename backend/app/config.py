"""Configuration for Nextup OSS.

Two layers:

* ``Settings``: feature settings with safe defaults. Every external integration is off.
  It can be constructed directly (tests do), but then it has **no database identity**
  and ``database_url`` refuses.
* ``load_settings(environ)``: the only way a process gets real configuration. It
  reads ``NEXTUP_*`` names only, refuses legacy names, loads ``*_FILE`` secrets, and
  requires an explicit deployment identity. ``get_settings()`` wraps it.

No setting value ever appears in an error, a log line or ``repr``.
"""

import logging
import re
import urllib.parse
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from os import environ as _process_environ

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, SecretStr, ValidationError

from app.guard.errors import ConfigError
from app.secrets_files import read_from_environ

logger = logging.getLogger(__name__)

ENVIRONMENTS = ("dev", "staging", "ci", "test")
# Role/name prefix and expected cluster per environment. ``test`` runs inside the CI cluster.
ENV_PREFIX = {"dev": "nextup_dev", "staging": "nextup_stg", "ci": "nextup_ci", "test": "nextup_ci"}
EXPECTED_CLUSTER = {
    "dev": "nextup-oss-dev",
    "staging": "nextup-oss-stg",
    "ci": "nextup-ci",
    "test": "nextup-ci",
}
TEST_DATABASE = re.compile(r"^nextup_(ci|migration_test_[0-9a-f]{32})$")
DB_HOST = "postgres"
DB_PORT = 5432
REDIS_URL = "redis://redis:6379/0"
PASSWORD = re.compile(r"^[A-Za-z0-9_-]{24,256}$")
KNOWN_PLACEHOLDERS = frozenset(
    {"local-development", "synthetic-ci-only", "ci-synthetic", "change-me", "changeme", "password"}
)

# Names from earlier single-stack layouts. Their presence means a foreign env file,
# inherited stack variables or a copied shell; refuse rather than ignore.
LEGACY_VARIABLES = frozenset(
    {
        "DATABASE_URL",
        "POSTGRES_PASSWORD",
        "POSTGRES_USER",
        "POSTGRES_DB",
        "POSTGRES_HOST",
        "PGPASSWORD",
        "PGHOST",
        "PGUSER",
        "PGDATABASE",
        "PGSERVICEFILE",
        "PGPASSFILE",
        "GMAIL_REFRESH_TOKEN",
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GMAIL_SYNC_ENABLED",
        "CALENDAR_SYNC_ENABLED",
        "ADZUNA_APP_ID",
        "ADZUNA_APP_KEY",
        "GREENHOUSE_BOARD_TOKEN",
        "LIVE_JOB_FETCH_ENABLED",
        "FIXTURE_FETCH_ENABLED",
    }
)
LEGACY_PATTERN = re.compile(r"(^|_)N8N(_|$)")

SECRET_FIELDS = (
    "adzuna_app_id",
    "adzuna_app_key",
    "google_oauth_client_id",
    "google_oauth_client_secret",
    "gmail_refresh_token",
)
GOOGLE_FIELDS = ("google_oauth_client_id", "google_oauth_client_secret", "gmail_refresh_token")
ADZUNA_FIELDS = ("adzuna_app_id", "adzuna_app_key")
PLAIN_FIELDS = (
    "diagnostic_interval_seconds",
    "live_job_fetch_enabled",
    "fixture_data_mode",
    "job_fetch_min_interval_seconds",
    "greenhouse_board_token",
    "greenhouse_company_name",
    "job_retention_days",
    "task_history_cleanup_enabled",
    "task_history_retention_days",
    "task_history_batch_size",
    "gmail_sync_enabled",
    "gmail_sync_interval_seconds",
    "calendar_sync_enabled",
    "calendar_sync_interval_seconds",
    "external_classifier_enabled",
)
BOOLEAN_FIELDS = frozenset(
    name for name in PLAIN_FIELDS if name.endswith("_enabled") or name == "fixture_data_mode"
)


def env_name(field_name: str) -> str:
    return "NEXTUP_" + field_name.upper()


# Explicit allowlist: unknown NEXTUP_* keys are refused, never ignored.
# Every NEXTUP_* variable a backend process sees must be one of these.
IDENTITY_KEYS = frozenset(
    {
        "NEXTUP_ENV",
        "NEXTUP_INSTANCE_ID",
        "NEXTUP_DB_HOST",
        "NEXTUP_DB_PORT",
        "NEXTUP_DB_NAME",
        "NEXTUP_DB_USER",
        "NEXTUP_DB_PASSWORD",
        "NEXTUP_DB_PASSWORD_FILE",
        "NEXTUP_DB_ROLE",
        "NEXTUP_DATABASE_URL",
        "NEXTUP_DATABASE_URL_FILE",
        "NEXTUP_REDIS_URL",
        "NEXTUP_MIGRATION_KEY",
        "NEXTUP_MIGRATION_KEY_FILE",
        "NEXTUP_SECRETS_DIR",
        "NEXTUP_ALEMBIC_OFFLINE_REVIEW",
    }
)
# Local-session setup code (docs/decisions/0001-local-session-boundary.md). File only: the
# inline name is not on the allowlist, so it is refused like any unknown key. It is not an
# integration credential and is deliberately outside SECRET_FIELDS.
SETUP_CODE_VARIABLE = "NEXTUP_SETUP_CODE"
FEATURE_KEYS = frozenset(
    {env_name(n) for n in PLAIN_FIELDS}
    | {env_name(n) for n in SECRET_FIELDS}
    | {env_name(n) + "_FILE" for n in SECRET_FIELDS}
    | {SETUP_CODE_VARIABLE + "_FILE"}
)
# Test-harness variables share the namespace; they are accepted only in ci and test.
HARNESS_KEYS = frozenset(
    {
        "NEXTUP_TEST_SCHEMA",
        "NEXTUP_TEST_QUEUE",
        "NEXTUP_TEST_BLOCK",
        "NEXTUP_TEST_SOCKET",
        "NEXTUP_INTEGRATION_APPROVED",
        "NEXTUP_CI_REQUIRE_PROFILE",
        "NEXTUP_CI_RETENTION",
        "NEXTUP_PROTECTED_RESOURCES_FILE",
    }
)
ALLOWED_KEYS = IDENTITY_KEYS | FEATURE_KEYS


def _refuse_unknown(environ, env) -> None:
    allowed = ALLOWED_KEYS | (HARNESS_KEYS if env in ("ci", "test") else frozenset())
    unknown = sorted(k for k in environ if k.startswith("NEXTUP_") and k not in allowed)
    if unknown:
        raise ConfigError("NXG-C16", keys=tuple(unknown), env=env)
    review = environ.get("NEXTUP_ALEMBIC_OFFLINE_REVIEW")
    if review is not None and review != "1":
        raise ConfigError("NXG-C14", keys=("NEXTUP_ALEMBIC_OFFLINE_REVIEW",), env=env)


class Settings(BaseModel):
    """Feature settings. Integrations default off; no database identity by default."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    redis_url: str = REDIS_URL
    # Empty when no setup code file is mounted; local sessions then cannot be started.
    setup_code: SecretStr = SecretStr("")
    diagnostic_interval_seconds: int = Field(default=60, ge=10, le=3600)
    live_job_fetch_enabled: bool = False
    # Fixture data mode (ci/test only): every job source serves the bundled synthetic
    # fixtures and every live provider request is refused. Mutually exclusive with live
    # fetching and with any provider credential.
    fixture_data_mode: bool = False
    adzuna_app_id: SecretStr = SecretStr("")
    adzuna_app_key: SecretStr = SecretStr("")
    job_fetch_min_interval_seconds: int = Field(default=60, ge=10, le=3600)
    greenhouse_board_token: str = Field(default="", pattern=r"^[a-zA-Z0-9_-]{0,100}$")
    greenhouse_company_name: str = Field(default="", max_length=300)
    job_retention_days: int = Field(default=30, ge=1, le=365)
    task_history_cleanup_enabled: bool = False
    task_history_retention_days: int = Field(default=30, ge=7, le=3650)
    task_history_batch_size: int = Field(default=100, ge=1, le=500)
    # Read-only Gmail correspondence sync; every value defaults off or empty.
    gmail_sync_enabled: bool = False
    google_oauth_client_id: SecretStr = SecretStr("")
    google_oauth_client_secret: SecretStr = SecretStr("")
    gmail_refresh_token: SecretStr = SecretStr("")
    gmail_sync_interval_seconds: int = Field(default=300, ge=60, le=3600)
    # Read-only Google Calendar sync shares the OAuth client and refresh token above.
    calendar_sync_enabled: bool = False
    calendar_sync_interval_seconds: int = Field(default=900, ge=60, le=3600)
    # External email classifier. Consumed by the database guard.
    external_classifier_enabled: bool = False

    _identity: "DeploymentIdentity | None" = PrivateAttr(default=None)

    @property
    def identity(self) -> "DeploymentIdentity":
        if self._identity is None:
            raise ConfigError("NXG-C11")
        return self._identity

    @property
    def database_url(self):
        """SQLAlchemy URL object for this process's role. There is no default."""
        return self.identity.database.sqlalchemy_url()


@dataclass(frozen=True)
class DatabaseIdentity:
    host: str
    port: int
    name: str
    user: str
    password: SecretStr = field(repr=False)

    def sqlalchemy_url(self):
        from sqlalchemy.engine import URL  # noqa: PLC0415 - keep config importable without SQLAlchemy

        return URL.create(
            "postgresql+psycopg",
            username=self.user,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.name,
        )

    def __repr__(self):
        return f"DatabaseIdentity(name={self.name!r}, user={self.user!r})"


@dataclass(frozen=True)
class DeploymentIdentity:
    environment: str
    role: str  # "runtime" or "migrator"
    instance_id: uuid.UUID | None
    database: DatabaseIdentity = field(repr=False)
    expected_cluster: str
    migration_key: SecretStr | None = field(default=None, repr=False)

    @property
    def expected_user(self) -> str:
        suffix = "app" if self.role == "runtime" else "owner"
        return f"{ENV_PREFIX[self.environment]}_{suffix}"

    def __repr__(self):
        return (
            f"DeploymentIdentity(environment={self.environment!r}, role={self.role!r}, "
            f"database={self.database.name!r})"
        )


# ---------- loader ----------


def _refuse_legacy(environ):
    found = sorted(k for k in environ if k in LEGACY_VARIABLES or LEGACY_PATTERN.search(k))
    if found:
        raise ConfigError("NXG-C03", keys=tuple(found))


# libpq (psycopg) fills every connection parameter the application does not pass from the
# process environment: PGHOSTADDR overrides the address behind an approved host name,
# PGSERVICE / PGSERVICEFILE / PGSYSCONFDIR pull parameters from a file, PGOPTIONS, PGTZ,
# PGDATESTYLE and PGCLIENTENCODING plant session settings, PGSSL* / PGREQUIREAUTH /
# PGCHANNELBINDING change how the server is authenticated. The application passes host, port,
# database, user, password, timeout and options itself, so no client variable is needed and
# none is accepted.
#
# The rule is a pattern, not a list, so a variable added by a later libpq is refused too:
# every name of the form PG<letter>... is refused unless it is allowlisted below. libpq reads
# the real process environment, whatever mapping the loader was given, so both are checked.
# Only names are ever reported, never values.
LIBPQ_VARIABLE = re.compile(r"^PG[A-Z][A-Z0-9_]*$")
# Client variables that application processes (api, worker, scheduler, migrator) may carry.
LIBPQ_ALLOWED_VARIABLES: frozenset[str] = frozenset()
# Not read by libpq: the server's data directory. Meaningless to these processes, harmless.
SERVER_ONLY_VARIABLES = frozenset({"PGDATA"})


def libpq_variables(names) -> list[str]:
    """The PostgreSQL client variables among ``names`` that are not allowed."""
    permitted = LIBPQ_ALLOWED_VARIABLES | SERVER_ONLY_VARIABLES
    return sorted(k for k in names if LIBPQ_VARIABLE.fullmatch(k) and k not in permitted)


def refuse_client_environment(environ=None):
    """Raise NXG-C18 if a PostgreSQL client variable is set. Called by the loader and again
    wherever an engine is created, so nothing set after start-up reaches a connection."""
    found = set(libpq_variables(_process_environ))
    if environ is not None:
        found.update(libpq_variables(environ))
    if found:
        raise ConfigError("NXG-C18", keys=tuple(sorted(found)))


def _environment(environ) -> str:
    value = environ.get("NEXTUP_ENV")
    if value == "personal":
        raise ConfigError("NXG-C02")
    if value not in ENVIRONMENTS:
        raise ConfigError("NXG-C01")
    return value


def _secret(environ, variable, *, env, allow_inline):
    value = read_from_environ(environ, variable)
    if value is not None and environ.get(variable) is not None and not allow_inline:
        raise ConfigError("NXG-C15", keys=(variable,), env=env)
    return value


def _parse_url(raw: str):
    try:
        parts = urllib.parse.urlsplit(raw)
        port = parts.port
    except ValueError:
        raise ConfigError("NXG-C14", keys=("NEXTUP_DATABASE_URL",)) from None
    if parts.scheme not in ("postgresql", "postgresql+psycopg"):
        raise ConfigError("NXG-C14", keys=("NEXTUP_DATABASE_URL",))
    if parts.query or parts.fragment:
        # libpq honours host=, sslmode=, service= in the query; never accept overrides.
        raise ConfigError("NXG-C14", keys=("NEXTUP_DATABASE_URL",))
    name = parts.path.lstrip("/")
    return (
        parts.hostname or "",
        port or DB_PORT,
        urllib.parse.unquote(name),
        urllib.parse.unquote(parts.username or ""),
        urllib.parse.unquote(parts.password or ""),
    )


def _database(environ, env, role, allow_inline) -> DatabaseIdentity:
    url = _secret(environ, "NEXTUP_DATABASE_URL", env=env, allow_inline=allow_inline)
    component_keys = ("NEXTUP_DB_HOST", "NEXTUP_DB_PORT", "NEXTUP_DB_NAME", "NEXTUP_DB_USER")
    password_keys = ("NEXTUP_DB_PASSWORD", "NEXTUP_DB_PASSWORD_FILE")
    present = [k for k in component_keys + password_keys if k in environ]
    if url is not None and present:
        raise ConfigError("NXG-C04", keys=("NEXTUP_DATABASE_URL", *present))
    if url is not None:
        host, port, name, user, password = _parse_url(url)
    else:
        missing = [
            k for k in ("NEXTUP_DB_HOST", "NEXTUP_DB_NAME", "NEXTUP_DB_USER") if not environ.get(k)
        ]
        if missing:
            raise ConfigError("NXG-C13", keys=tuple(missing))
        host, name, user = (
            environ["NEXTUP_DB_HOST"],
            environ["NEXTUP_DB_NAME"],
            environ["NEXTUP_DB_USER"],
        )
        raw_port = environ.get("NEXTUP_DB_PORT", str(DB_PORT))
        if not raw_port.isdigit():
            raise ConfigError("NXG-C14", keys=("NEXTUP_DB_PORT",))
        port = int(raw_port)
        password = _secret(environ, "NEXTUP_DB_PASSWORD", env=env, allow_inline=allow_inline)
        if password is None:
            raise ConfigError("NXG-C13", keys=("NEXTUP_DB_PASSWORD_FILE",))

    if host != DB_HOST or port != DB_PORT:
        raise ConfigError("NXG-C07", env=env)
    prefix = ENV_PREFIX[env]
    expected_name_ok = TEST_DATABASE.fullmatch(name) if env == "test" else name == prefix
    expected_user = f"{prefix}_{'app' if role == 'runtime' else 'owner'}"
    if not expected_name_ok or user != expected_user:
        raise ConfigError("NXG-C12", env=env)
    if not PASSWORD.fullmatch(password or "") or password.lower() in KNOWN_PLACEHOLDERS:
        raise ConfigError("NXG-S06", env=env)
    return DatabaseIdentity(host, port, name, user, SecretStr(password))


def _identity(environ, env) -> DeploymentIdentity:
    allow_inline = env in ("dev", "ci", "test")
    role = environ.get("NEXTUP_DB_ROLE", "runtime")
    if role not in ("runtime", "migrator"):
        raise ConfigError("NXG-C14", keys=("NEXTUP_DB_ROLE",))
    key_present = any(k in environ for k in ("NEXTUP_MIGRATION_KEY", "NEXTUP_MIGRATION_KEY_FILE"))
    if role == "runtime" and key_present:
        raise ConfigError("NXG-C10", env=env)
    migration_key = None
    if role == "migrator":
        raw_key = _secret(environ, "NEXTUP_MIGRATION_KEY", env=env, allow_inline=allow_inline)
        if raw_key is None:
            raise ConfigError("NXG-C13", keys=("NEXTUP_MIGRATION_KEY_FILE",))
        if len(raw_key) < 32:
            raise ConfigError("NXG-S06", env=env)
        migration_key = SecretStr(raw_key)

    raw_instance = environ.get("NEXTUP_INSTANCE_ID")
    instance_id = None
    if raw_instance:
        try:
            instance_id = uuid.UUID(raw_instance)
        except ValueError:
            raise ConfigError("NXG-C14", keys=("NEXTUP_INSTANCE_ID",)) from None
        if instance_id.version != 4:
            raise ConfigError("NXG-C14", keys=("NEXTUP_INSTANCE_ID",))
    elif env == "staging":
        raise ConfigError("NXG-C13", keys=("NEXTUP_INSTANCE_ID",))

    return DeploymentIdentity(
        environment=env,
        role=role,
        instance_id=instance_id,
        database=_database(environ, env, role, allow_inline),
        expected_cluster=EXPECTED_CLUSTER[env],
        migration_key=migration_key,
    )


def _feature_values(environ, env) -> dict:
    values: dict = {}
    allow_inline = env in ("dev", "ci", "test")
    for name in PLAIN_FIELDS:
        raw = environ.get(env_name(name))
        if raw is None:
            continue
        if name in BOOLEAN_FIELDS:
            if raw not in ("true", "false"):
                raise ConfigError("NXG-C14", keys=(env_name(name),))
            values[name] = raw == "true"
        else:
            values[name] = raw
    for name in SECRET_FIELDS:
        value = _secret(environ, env_name(name), env=env, allow_inline=allow_inline)
        if value is not None:
            values[name] = value
    setup_code = _secret(environ, SETUP_CODE_VARIABLE, env=env, allow_inline=False)
    if setup_code is not None:
        values["setup_code"] = setup_code
    redis = environ.get("NEXTUP_REDIS_URL")
    if redis is not None:
        if redis != REDIS_URL:
            raise ConfigError("NXG-C07", keys=("NEXTUP_REDIS_URL",), env=env)
        values["redis_url"] = redis
    return values


def _check_integrations(settings: Settings, env: str) -> None:
    def present(names):
        return [n for n in names if getattr(settings, n).get_secret_value()]

    google_on = settings.gmail_sync_enabled or settings.calendar_sync_enabled
    flags_on = [
        n
        for n in (
            "gmail_sync_enabled",
            "calendar_sync_enabled",
            "live_job_fetch_enabled",
            "fixture_data_mode",
            "external_classifier_enabled",
        )
        if getattr(settings, n)
    ]
    if env == "staging":
        if flags_on or present(SECRET_FIELDS) or settings.greenhouse_board_token:
            raise ConfigError(
                "NXG-C09",
                keys=tuple(env_name(n) for n in flags_on + present(SECRET_FIELDS)),
                env=env,
            )
        return
    if google_on and len(present(GOOGLE_FIELDS)) != len(GOOGLE_FIELDS):
        missing = [env_name(n) for n in GOOGLE_FIELDS if n not in present(GOOGLE_FIELDS)]
        raise ConfigError("NXG-C08", keys=tuple(missing), env=env)
    if settings.fixture_data_mode:
        if env not in ("ci", "test"):
            raise ConfigError("NXG-C08", keys=("NEXTUP_FIXTURE_DATA_MODE",), env=env)
        # Synthetic fixtures only: no live switch, no provider credential or board, no sync.
        conflicting = [
            env_name(n)
            for n in ("live_job_fetch_enabled", "gmail_sync_enabled", "calendar_sync_enabled")
            if getattr(settings, n)
        ] + [env_name(n) for n in present(SECRET_FIELDS)]
        if settings.greenhouse_board_token or settings.greenhouse_company_name:
            conflicting += [env_name("greenhouse_board_token"), env_name("greenhouse_company_name")]
        if conflicting:
            raise ConfigError("NXG-C17", keys=tuple(conflicting), env=env)
    if settings.external_classifier_enabled:
        # Not available in any OSS environment yet.
        raise ConfigError("NXG-C08", keys=("NEXTUP_EXTERNAL_CLASSIFIER_ENABLED",), env=env)
    idle = present(GOOGLE_FIELDS) if not google_on else []
    idle += present(ADZUNA_FIELDS) if not settings.live_job_fetch_enabled else []
    for name in idle:
        logger.info(
            "Configured credential is unused while its integration is disabled: %s", env_name(name)
        )


def load_settings(environ=None) -> Settings:
    """Build validated settings from an environment mapping (default: the process env)."""
    environ = _process_environ if environ is None else environ
    _refuse_legacy(environ)
    refuse_client_environment(environ)
    env = _environment(environ)
    _refuse_unknown(environ, env)
    identity = _identity(environ, env)
    try:
        settings = Settings(**_feature_values(environ, env))
    except ValidationError as exc:
        # ValidationError.errors()/json() still contain the input; expose field names only.
        keys = tuple(
            env_name(str(error["loc"][0]))
            for error in exc.errors(include_input=False)
            if error.get("loc")
        )
        raise ConfigError("NXG-C14", keys=keys, env=env) from None
    _check_integrations(settings, env)
    settings._identity = identity
    return settings


@lru_cache
def get_settings() -> Settings:
    return load_settings()
