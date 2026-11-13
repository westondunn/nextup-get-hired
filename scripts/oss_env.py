"""Nextup OSS environment identity and Compose isolation checks (standard library only).

Every supported Compose command names exactly one OSS environment. Identity values
(project, volume, image, database names) are literals in the overlay files, so no
environment variable can redirect them. Validation is allowlist-based: anything that
is not the selected environment's own resource fails closed. An optional, private
denylist file (never committed) can add known protected names on top.
"""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class IsolationError(RuntimeError):
    """A configuration could reach resources outside the selected OSS environment."""


@dataclass(frozen=True)
class Environment:
    name: str
    project: str
    overlay: str
    env_file: str
    example: str
    database: str
    prefix: str
    allowed_keys: tuple[str, ...]
    app_env: str  # NEXTUP_ENV inside the containers

    @property
    def files(self) -> tuple[str, ...]:
        return ("compose.base.yaml", self.overlay)

    @property
    def cluster(self) -> str:
        return self.project  # PostgreSQL cluster_name equals the project name

    def role(self, kind: str) -> str:
        return f"{self.database}_{kind}"

    @property
    def volume_prefix(self) -> str:
        return f"{self.project}_"

    @property
    def image_prefix(self) -> str:
        return f"{self.project}/"


# Env-file / stack-variable keys: non-secret values only (no password, token or key).
_COMMON_KEYS = (
    "INSTANCE_ID",
    "API_PORT",
    "FRONTEND_PORT",
    "DIAGNOSTIC_INTERVAL_SECONDS",
    "JOB_FETCH_MIN_INTERVAL_SECONDS",
    "JOB_RETENTION_DAYS",
    "TASK_HISTORY_CLEANUP_ENABLED",
    "TASK_HISTORY_RETENTION_DAYS",
    "TASK_HISTORY_BATCH_SIZE",
)
_DEV_ONLY_KEYS = ("LOCAL_UID", "LOCAL_GID")
_STAGING_ONLY_KEYS = ("SECRETS_DIR", "SECRETS_GID")

ENVIRONMENTS = {
    "dev": Environment(
        name="dev",
        project="nextup-oss-dev",
        overlay="compose.dev.yaml",
        env_file=".env.dev",
        example="env/dev.env.example",
        database="nextup_dev",
        prefix="NEXTUP_DEV_",
        allowed_keys=tuple(f"NEXTUP_DEV_{k}" for k in _COMMON_KEYS + _DEV_ONLY_KEYS),
        app_env="dev",
    ),
    "staging": Environment(
        name="staging",
        project="nextup-oss-stg",
        overlay="compose.staging.yaml",
        env_file=".env.staging",
        example="env/staging.env.example",
        database="nextup_stg",
        prefix="NEXTUP_STG_",
        allowed_keys=tuple(f"NEXTUP_STG_{k}" for k in _COMMON_KEYS + _STAGING_ONLY_KEYS),
        app_env="staging",
    ),
}

OSS_PROJECT = re.compile(r"^nextup-oss-(dev|stg)$")
CI_PROJECT = re.compile(r"^nextup-ci-[0-9a-f]{12}$")
PASSWORD = re.compile(r"^[A-Za-z0-9_-]{24,256}$")
UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
KNOWN_PLACEHOLDERS = frozenset(
    {"local-development", "synthetic-ci-only", "ci-synthetic", "change-me", "changeme", "password"}
)
# Ports used by the previous single-stack layout. OSS environments never reuse them.
LEGACY_DEFAULT_PORTS = frozenset({5173, 5174, 5678, 5679, 8000})
PINNED_SERVICE_IMAGES = frozenset({"postgres:17-bookworm", "redis:7.4-bookworm"})
RUNTIME_SERVICES = ("api", "worker", "scheduler")
BACKEND_SERVICES = RUNTIME_SERVICES + ("migrate",)

# Secrets: Compose `secrets:` read from files; containers see /run/secrets/<name> only.
SECRET_NAMES = ("db_admin_password", "db_owner_password", "db_app_password", "migration_key")
SERVICE_SECRETS = {
    "postgres": {"db_admin_password", "db_owner_password", "db_app_password"},
    "migrate": {"db_owner_password", "migration_key"},
    **{name: {"db_app_password"} for name in RUNTIME_SERVICES},
}
INIT_SCRIPT_DIR = "backend/docker/initdb"
INIT_MOUNT_TARGET = "/docker-entrypoint-initdb.d"
GUARD_ENTRYPOINT = ["python", "-m", "app.guard"]
INTEGRATION_FLAGS = (
    "NEXTUP_FIXTURE_DATA_MODE",
    "NEXTUP_GMAIL_SYNC_ENABLED",
    "NEXTUP_CALENDAR_SYNC_ENABLED",
    "NEXTUP_LIVE_JOB_FETCH_ENABLED",
    "NEXTUP_EXTERNAL_CLASSIFIER_ENABLED",
)
# Mirror of the backend allowlist (backend/app/config.py) restricted to what Compose may
# set. Anything else in a backend service environment fails validation.
BACKEND_ENV_KEYS = frozenset(
    {
        "NEXTUP_ENV",
        "NEXTUP_INSTANCE_ID",
        "NEXTUP_DB_HOST",
        "NEXTUP_DB_PORT",
        "NEXTUP_DB_NAME",
        "NEXTUP_DB_USER",
        "NEXTUP_DB_PASSWORD_FILE",
        "NEXTUP_DB_ROLE",
        "NEXTUP_MIGRATION_KEY_FILE",
        "NEXTUP_REDIS_URL",
        "NEXTUP_DIAGNOSTIC_INTERVAL_SECONDS",
        "NEXTUP_JOB_FETCH_MIN_INTERVAL_SECONDS",
        "NEXTUP_JOB_RETENTION_DAYS",
        "NEXTUP_TASK_HISTORY_CLEANUP_ENABLED",
        "NEXTUP_TASK_HISTORY_RETENTION_DAYS",
        "NEXTUP_TASK_HISTORY_BATCH_SIZE",
        *INTEGRATION_FLAGS,
    }
)
SECRET_SUFFIXES = ("PASSWORD", "SECRET", "TOKEN", "KEY")
# Names from earlier single-stack layouts (mirrors backend LEGACY_VARIABLES).
LEGACY_NAMES = frozenset(
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
        "PGOPTIONS",
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
        "REDIS_URL",
    }
)
LEGACY_PATTERN = re.compile(r"(^|_)N8N(_|$)")
# PostgreSQL client (libpq) variables: PGHOSTADDR, PGSERVICE, PGOPTIONS, PGSSLMODE and the rest
# would change where and how a container connects. The rule is the backend's (app.config):
# every PG<letter>... name is refused. PGDATA is not a client variable; it is accepted in the
# shell and, in a rendered stack, only on the postgres service.
LIBPQ_VARIABLE = re.compile(r"^PG[A-Z][A-Z0-9_]*$")
SERVER_ONLY_VARIABLES = frozenset({"PGDATA"})


def libpq_names(names, *, server=False) -> list[str]:
    """PostgreSQL client variables among ``names``. ``server`` permits the server-only names."""
    permitted = SERVER_ONLY_VARIABLES if server else frozenset()
    return sorted(k for k in names if LIBPQ_VARIABLE.fullmatch(k) and k not in permitted)


# Variables that would let a shell silently change which project or files Compose uses.
FORBIDDEN_PROCESS_VARIABLES = (
    "COMPOSE_PROJECT_NAME",
    "COMPOSE_FILE",
    "COMPOSE_PATH_SEPARATOR",
    "COMPOSE_PROFILES",
    "COMPOSE_ENV_FILES",
)
# Only these reach the Compose process; credentials and config never come from the shell.
PASSTHROUGH_VARIABLES = (
    "PATH",
    "HOME",
    "USER",
    "LANG",
    "LC_ALL",
    "TERM",
    "TMPDIR",
    "XDG_RUNTIME_DIR",
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_CONFIG",
    "DOCKER_CERT_PATH",
    "DOCKER_TLS_VERIFY",
)
PROTECTED_FILE_VARIABLE = "NEXTUP_PROTECTED_RESOURCES_FILE"
SHELL_ALLOWED_NEXTUP_VARIABLES = frozenset({PROTECTED_FILE_VARIABLE})


def get_environment(name: str) -> Environment:
    try:
        return ENVIRONMENTS[name]
    except KeyError:
        raise IsolationError(
            f"Unknown or missing OSS environment {name!r}; choose one of: "
            + ", ".join(sorted(ENVIRONMENTS))
        ) from None


# ---------- Process environment ----------


def check_process_environment(environ) -> None:
    """Refuse shell settings that would make the selected stack ambiguous."""
    set_forbidden = [k for k in FORBIDDEN_PROCESS_VARIABLES if environ.get(k)]
    if set_forbidden:
        raise IsolationError(
            "Refusing: unset " + ", ".join(set_forbidden) + "; the OSS scripts select the "
            "Compose project and files explicitly."
        )
    shadowing = sorted(
        k for k in environ if k.startswith(tuple(e.prefix for e in ENVIRONMENTS.values()))
    )
    if shadowing:
        raise IsolationError(
            "Refusing: environment-specific settings belong in the selected env file, "
            "not the shell: " + ", ".join(shadowing)
        )
    # Application settings never come from the launcher's shell, and the raw-Compose
    # tripwire must not be disarmed. Only the private protected-resource list is accepted.
    overrides = sorted(
        k for k in environ if k.startswith("NEXTUP_") and k not in SHELL_ALLOWED_NEXTUP_VARIABLES
    )
    legacy = sorted(
        {k for k in environ if k in LEGACY_NAMES or LEGACY_PATTERN.search(k)}
        | set(libpq_names(environ, server=True))
    )
    if overrides or legacy:
        raise IsolationError(
            "Refusing: unsupported overrides in the shell (unset them): "
            + ", ".join(overrides + legacy)
        )


def child_environment(environ) -> dict[str, str]:
    return {k: environ[k] for k in PASSTHROUGH_VARIABLES if k in environ}


# ---------- Protected resources (optional private denylist) ----------


def load_protected(path: str | os.PathLike | None) -> dict[str, frozenset]:
    empty = {k: frozenset() for k in ("projects", "volumes", "images", "databases", "db_users")}
    empty["ports"] = frozenset()
    empty["networks"] = frozenset()
    # Optional absolute filesystem paths that CI scratch/evidence must never touch
    # (for example the original private repository); never named in OSS code.
    empty["paths"] = frozenset()
    if not path:
        return empty
    file = Path(path)
    if not file.is_file() or file.is_symlink():
        raise IsolationError(f"{PROTECTED_FILE_VARIABLE} is not a regular file")
    try:
        file.resolve().relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise IsolationError("The protected-resource list must live outside the repository")
    data = json.loads(file.read_text())
    result = dict(empty)
    for key in result:
        values = data.get(key, [])
        if key == "ports":
            result[key] = frozenset(int(v) for v in values)
        elif key == "paths":
            if not all(isinstance(v, str) and os.path.isabs(v) for v in values):
                raise IsolationError("Protected paths must be absolute")
            result[key] = frozenset(os.path.normpath(v) for v in values)
        else:
            result[key] = frozenset(values)
    return result


# ---------- Env files ----------


def parse_env_file(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export ") or "=" not in line:
            raise IsolationError(f"Env file line {number}: expected KEY=value")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise IsolationError(f"Env file line {number}: invalid key")
        if key in values:
            raise IsolationError(f"Env file line {number}: duplicate key {key}")
        values[key] = value.strip()
    return values


def validate_env_values(
    values: dict[str, str], env: Environment, *, require_identity=True, root=None
):
    """Only the selected environment's own, non-secret keys."""
    unknown = sorted(set(values) - set(env.allowed_keys))
    if unknown:
        raise IsolationError(
            f"Env file for {env.name} contains keys outside its allowlist: " + ", ".join(unknown)
        )
    p = env.prefix
    if require_identity:
        if not UUID4.fullmatch(values.get(f"{p}INSTANCE_ID", "")):
            raise IsolationError(f"{p}INSTANCE_ID must be a newly generated lowercase UUID4")
        numeric = ("LOCAL_UID", "LOCAL_GID") if env.name == "dev" else ("SECRETS_GID",)
        for suffix in numeric:
            raw = values.get(f"{p}{suffix}", "")
            if not raw.isdigit() or int(raw) == 0:
                raise IsolationError(f"{p}{suffix} must be a non-zero numeric ID")
        if env.name == "staging":
            check_secrets_dir_value(values.get(f"{p}SECRETS_DIR", ""), root=root)
    for suffix in ("API_PORT", "FRONTEND_PORT"):
        raw = values.get(f"{env.prefix}{suffix}")
        if raw:
            if not raw.isdigit():
                raise IsolationError(f"{env.prefix}{suffix} must be a port number")
            _check_port(int(raw), frozenset())


def check_env_file(path: Path, env: Environment) -> dict[str, str]:
    if path.is_symlink() or not path.is_file():
        raise IsolationError(f"{path.name} must be a regular, repository-local file")
    if path.stat().st_mode & 0o077:
        raise IsolationError(f"{path.name} must not be readable by group or others (chmod 600)")
    values = parse_env_file(path.read_text())
    validate_env_values(values, env, root=path.parent)
    return values


def check_secrets_dir_value(value: str, *, root=None) -> None:
    """Staging: an absolute host directory outside the repository (names only in errors)."""
    if not value or not value.startswith("/") or ".." in value.split("/") or "$" in value:
        raise IsolationError("NEXTUP_STG_SECRETS_DIR must be an absolute host path")
    repo = Path(root or ROOT).resolve()
    candidate = Path(os.path.normpath(value))
    if candidate == repo or repo in candidate.parents:
        raise IsolationError("NEXTUP_STG_SECRETS_DIR must be outside the repository")


# ---------- Dev secret files (generated by the launcher; never printed) ----------

DEV_SECRETS_DIR = ".secrets/dev"


def check_dev_secret_files(root: Path, *, uid=None) -> None:
    """Directory 0700 and files 0600, regular, owned by the launcher user, well-formed,
    pairwise distinct. Errors name the file only, never the content."""
    uid = os.getuid() if uid is None else uid
    directory = Path(root) / DEV_SECRETS_DIR
    for path in (directory.parent, directory):
        if path.is_symlink() or not path.is_dir():
            raise IsolationError(f"{path.relative_to(root)} must be a real directory")
        info = path.stat()
        if info.st_uid != uid or info.st_mode & 0o077:
            raise IsolationError(f"{path.relative_to(root)} must be owned by you with mode 0700")
    values = []
    for name in SECRET_NAMES:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise IsolationError(f"{DEV_SECRETS_DIR}/{name} is missing or not a regular file")
        info = path.stat()
        if info.st_uid != uid or info.st_mode & 0o177:
            raise IsolationError(f"{DEV_SECRETS_DIR}/{name} must be owned by you with mode 0600")
        value = path.read_text().removesuffix("\n")
        if not PASSWORD.fullmatch(value) or value.lower() in KNOWN_PLACEHOLDERS:
            raise IsolationError(f"{DEV_SECRETS_DIR}/{name} does not meet the strength rules")
        values.append(value)
    if len(set(values)) != len(values):
        raise IsolationError(f"{DEV_SECRETS_DIR}: every secret must be distinct")


# ---------- Compose configuration ----------


def _check_port(port: int, protected: frozenset) -> None:
    if not 1024 <= port <= 65535:
        raise IsolationError(f"Port {port} is outside 1024-65535")
    if port in LEGACY_DEFAULT_PORTS or port in protected:
        raise IsolationError(f"Port {port} is reserved for another stack")


def _ports(service) -> list[dict]:
    result = []
    for port in service.get("ports", []) or []:
        if isinstance(port, dict):
            result.append(
                {
                    "host_ip": str(port.get("host_ip", "")),
                    "published": str(port.get("published", "")),
                    "target": str(port.get("target", "")),
                }
            )
            continue
        parts = str(port).split(":")
        if len(parts) != 3:
            raise IsolationError(f"Port {port!r} must state host address, host port and target")
        result.append({"host_ip": parts[0], "published": parts[1], "target": parts[2]})
    return result


def _mounts(service) -> list[dict]:
    result = []
    for mount in service.get("volumes", []) or []:
        if isinstance(mount, dict):
            result.append(
                {
                    "type": mount.get("type", "volume"),
                    "source": str(mount.get("source", "")),
                    "target": str(mount.get("target", "")),
                    "read_only": bool(mount.get("read_only")),
                }
            )
            continue
        parts = str(mount).split(":")
        source, target = parts[0], parts[1] if len(parts) > 1 else parts[0]
        kind = "bind" if source.startswith((".", "/", "~", "$")) else "volume"
        result.append(
            {
                "type": kind,
                "source": source,
                "target": target,
                "read_only": len(parts) > 2 and "ro" in parts[2].split(","),
            }
        )
    return result


def _environment(service) -> dict[str, str]:
    value = service.get("environment") or {}
    if isinstance(value, list):
        value = dict(item.split("=", 1) if "=" in item else (item, "") for item in value)
    return {k: "" if v is None else str(v) for k, v in value.items()}


def _depends(service) -> set[str]:
    value = service.get("depends_on") or {}
    return set(value) if isinstance(value, (dict, list)) else set()


def _service_secrets(service) -> dict[str, str]:
    """source name -> target path, for short (`- name`) and rendered long forms."""
    result = {}
    for item in service.get("secrets") or []:
        if isinstance(item, dict):
            source = str(item.get("source", ""))
            target = str(item.get("target") or f"/run/secrets/{source}")
        else:
            source, target = str(item), f"/run/secrets/{item}"
        if not target.startswith("/"):
            target = f"/run/secrets/{target}"
        result[source] = target
    return result


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return value.split()
    return [str(v) for v in value]


def _bind_allowed(env: Environment, service: str, mount: dict) -> bool:
    source = mount["source"].rstrip("/")
    if service == "postgres" and mount["target"] == INIT_MOUNT_TARGET:
        return mount["read_only"] and source.endswith(INIT_SCRIPT_DIR)
    if env.name != "dev":
        return False
    if service in ("api", "worker") and mount["target"] == "/app/app":
        return mount["read_only"] and source.endswith("backend/app")
    if service == "e2e" and mount["target"] == "/app/test-results":
        return source.endswith("frontend/test-results")
    return False


def validate_config(config: dict, env: Environment, protected=None) -> None:
    """Validate a merged Compose model (docker JSON or the static merge below)."""
    protected = protected or load_protected(None)

    def fail(message):
        raise IsolationError(f"{env.name}: {message}")

    name = config.get("name")
    if name != env.project or not OSS_PROJECT.fullmatch(str(name)):
        fail(f"project resolves to {name!r}, expected {env.project!r}")
    if name in protected["projects"]:
        fail("project name is protected")

    volumes = config.get("volumes") or {}
    for key, volume in volumes.items():
        volume = volume or {}
        if volume.get("external"):
            fail(f"volume {key} is external")
        vname = volume.get("name")
        if not vname or not str(vname).startswith(env.volume_prefix):
            fail(f"volume {key} needs an explicit name starting with {env.volume_prefix}")
        if vname in protected["volumes"]:
            fail(f"volume {key} uses a protected name")

    networks = config.get("networks") or {}
    for key, network in networks.items():
        network = network or {}
        if network.get("external"):
            fail(f"network {key} is external")
        if network.get("name") and not str(network["name"]).startswith(env.volume_prefix):
            fail(f"network {key} has a foreign name")
        if network.get("name") in protected["networks"]:
            fail(f"network {key} uses a protected name")
    if env.name == "staging" and not (networks.get("backend") or {}).get("internal"):
        fail("staging needs an internal backend network")

    services = config.get("services") or {}
    required = {"postgres", "redis", "api", "worker", "scheduler", "frontend", "migrate"}
    missing = required - set(services)
    if missing:
        fail("missing services: " + ", ".join(sorted(missing)))

    schedulers = []
    for sname, service in services.items():
        if service.get("container_name"):
            fail(f"{sname} sets container_name")
        if service.get("env_file"):
            fail(f"{sname} loads an env_file; values must come from the selected env file")
        # Every service: the backends connect through libpq, and the first-boot script runs
        # psql inside the postgres container.
        for key in libpq_names(_environment(service), server=sname == "postgres"):
            fail(f"{sname} receives the PostgreSQL client variable {key}")
        for flag in ("privileged", "pid", "ipc", "cap_add", "devices"):
            if service.get(flag):
                fail(f"{sname} sets {flag}")
        if str(service.get("network_mode", "")).startswith(("host", "container", "service")):
            fail(f"{sname} shares another network namespace")
        image = str(service.get("image", ""))
        if service.get("build"):
            if not image.startswith(env.image_prefix):
                fail(f"{sname} image must start with {env.image_prefix}")
            if image.split(":")[0] in protected["images"]:
                fail(f"{sname} uses a protected image name")
        elif image not in PINNED_SERVICE_IMAGES:
            fail(f"{sname} uses an unexpected image")
        if env.name == "staging" and sname in ("postgres", "redis", "worker", "scheduler"):
            nets = service.get("networks") or {}
            if set(nets) != {"backend"}:
                fail(f"{sname} must join only the internal backend network")

        for port in _ports(service):
            if sname in ("postgres", "redis"):
                fail(f"{sname} publishes a host port")
            if port["host_ip"] != "127.0.0.1":
                fail(f"{sname} port is not bound to 127.0.0.1")
            if not port["published"].isdigit():
                fail(f"{sname} publishes an unresolved or dynamic port")
            try:
                _check_port(int(port["published"]), protected["ports"])
            except IsolationError as exc:
                fail(f"{sname}: {exc}")

        for mount in _mounts(service):
            if "docker.sock" in mount["source"] or "docker.sock" in mount["target"]:
                fail(f"{sname} mounts the Docker socket")
            if mount["type"] == "volume":
                if mount["source"] not in volumes:
                    fail(f"{sname} mounts an undeclared volume")
            elif mount["type"] == "bind":
                if not _bind_allowed(env, sname, mount):
                    fail(f"{sname} has a host bind mount that is not allowlisted")
            elif mount["type"] != "tmpfs":
                fail(f"{sname} has an unsupported mount type")

        if "migrate" in _depends(service):
            fail(f"{sname} waits for migrations; startup must not migrate")
        command = service.get("command") or []
        if isinstance(command, str):
            command = command.split()
        if "beat" in command:
            schedulers.append(sname)

        values = _environment(service)
        secrets = _service_secrets(service)
        if set(secrets) != SERVICE_SECRETS.get(sname, set()):
            expected = sorted(SERVICE_SECRETS.get(sname, set()))
            fail(f"{sname} receives secrets {sorted(secrets)}, expected {expected}")
        for source, target in secrets.items():
            if target != f"/run/secrets/{source}":
                fail(f"{sname} mounts secret {source} at an unexpected path")
        if sname in BACKEND_SERVICES:
            _validate_backend(fail, sname, service, values, env, protected)
        elif sname != "postgres" and any(
            k.startswith(("NEXTUP_DB_", "NEXTUP_MIGRATION", "POSTGRES_")) for k in values
        ):
            fail(f"{sname} must not receive database settings")

    _validate_postgres(fail, services["postgres"], env, protected)
    if schedulers != ["scheduler"]:
        fail(f"expected exactly one beat scheduler, got {schedulers}")

    migrate = services["migrate"]
    if "migrate" not in (migrate.get("profiles") or []):
        fail("migrate must sit behind the 'migrate' profile")
    if _as_list(migrate.get("entrypoint")) != GUARD_ENTRYPOINT:
        fail("migrate entrypoint must be the guard (python -m app.guard)")
    if _as_list(migrate.get("command")) != ["plan"]:
        fail("migrate default command must be the read-only plan")
    if migrate.get("ports"):
        fail("migrate publishes a port")
    if str(migrate.get("restart", "no")) != "no":
        fail("migrate must not restart")

    _validate_secrets(fail, config.get("secrets") or {}, env)


def _validate_backend(fail, sname, service, values, env, protected) -> None:
    """Credential and guard contract for api, worker, scheduler and migrate."""
    unknown = sorted(set(values) - BACKEND_ENV_KEYS)
    if unknown:
        fail(f"{sname} environment has keys outside the backend allowlist: " + ", ".join(unknown))
    for key in values:
        if key in LEGACY_NAMES or LEGACY_PATTERN.search(key):
            fail(f"{sname} receives the legacy variable {key}")
        if key.endswith(SECRET_SUFFIXES) and not key.endswith("_FILE"):
            fail(f"{sname} receives an inline secret variable {key}")
    expected = {
        "NEXTUP_ENV": env.app_env,
        "NEXTUP_DB_HOST": "postgres",
        "NEXTUP_DB_PORT": "5432",
        "NEXTUP_DB_NAME": env.database,
        "NEXTUP_REDIS_URL": "redis://redis:6379/0",
        **{flag: "false" for flag in INTEGRATION_FLAGS},
    }
    if sname == "migrate":
        expected.update(
            NEXTUP_DB_ROLE="migrator",
            NEXTUP_DB_USER=env.role("owner"),
            NEXTUP_DB_PASSWORD_FILE="/run/secrets/db_owner_password",
            NEXTUP_MIGRATION_KEY_FILE="/run/secrets/migration_key",
        )
    else:
        expected.update(
            NEXTUP_DB_USER=env.role("app"),
            NEXTUP_DB_PASSWORD_FILE="/run/secrets/db_app_password",
        )
        for key in ("NEXTUP_DB_ROLE", "NEXTUP_MIGRATION_KEY_FILE"):
            if key in values:
                fail(f"{sname} is a runtime service and must not set {key}")
    for key, value in expected.items():
        if values.get(key) != value:
            fail(f"{sname} must set {key}={value}")
    user = values.get("NEXTUP_DB_USER")
    if user in protected["db_users"] or env.database in protected["databases"]:
        fail(f"{sname} uses a protected database identity")
    if not UUID4.fullmatch(values.get("NEXTUP_INSTANCE_ID", "")):
        fail(f"{sname} NEXTUP_INSTANCE_ID must be a UUID4")
    user = str(service.get("user") or "")
    groups = _as_list(service.get("group_add"))
    if env.name == "dev":
        if not re.fullmatch(r"[1-9]\d*:[1-9]\d*", user):
            fail(f"{sname} must run as the launcher's non-root UID:GID")
        if groups:
            fail(f"{sname} must not add groups in dev")
    else:
        if user:
            fail(f"{sname} must run as the image user in staging")
        if len(groups) != 1 or not re.fullmatch(r"[1-9]\d*", groups[0]):
            fail(f"{sname} must join exactly the numeric secrets group")
    if sname in RUNTIME_SERVICES:
        restart = str(service.get("restart", "no"))
        wanted = "no" if env.name == "dev" else "on-failure:3"
        if restart != wanted:
            fail(f"{sname} restart policy must be {wanted}")
        if service.get("entrypoint"):
            fail(f"{sname} must keep the image's guard entrypoint")


def _validate_postgres(fail, postgres, env, protected) -> None:
    values = _environment(postgres)
    expected = {
        "POSTGRES_USER": env.role("admin"),
        "POSTGRES_DB": "postgres",
        "POSTGRES_PASSWORD_FILE": "/run/secrets/db_admin_password",
    }
    for key, value in expected.items():
        if values.get(key) != value:
            fail(f"postgres must set {key}={value}")
    for key in values:
        if key not in expected and key not in SERVER_ONLY_VARIABLES:
            fail(f"postgres sets an unexpected variable {key}")
    if env.role("admin") in protected["db_users"]:
        fail("postgres bootstrap user is protected")
    if _as_list(postgres.get("command")) != ["postgres", "-c", f"cluster_name={env.cluster}"]:
        fail(f"postgres must run with cluster_name={env.cluster} and nothing else")
    raw_entrypoint = postgres.get("entrypoint")
    entrypoint = [] if isinstance(raw_entrypoint, str) else _as_list(raw_entrypoint)
    script = entrypoint[2] if len(entrypoint) > 2 else ""
    if entrypoint[:2] != ["/bin/sh", "-ec"] or "exec docker-entrypoint.sh" not in script:
        fail("postgres entrypoint must hand over to the image's docker-entrypoint.sh")
    if any(word in script for word in ("echo", "cat ", "set -x", "printenv", "env ")):
        fail("postgres entrypoint must not print anything")
    mounts = _mounts(postgres)
    init = [m for m in mounts if m["target"] == INIT_MOUNT_TARGET]
    if len(init) != 1 or not init[0]["read_only"]:
        fail("postgres must mount the first-boot scripts read-only")
    tmpfs = [str(t).split(":")[0] for t in _as_list(postgres.get("tmpfs"))]
    if "/run/nextup-initdb" not in tmpfs:
        fail("postgres must copy init passwords to a tmpfs only")


def _validate_secrets(fail, secrets: dict, env) -> None:
    if set(secrets) != set(SECRET_NAMES):
        fail(f"top-level secrets must be exactly {sorted(SECRET_NAMES)}")
    for name, secret in secrets.items():
        secret = secret or {}
        if set(secret) - {"file", "name"} or not secret.get("file"):
            fail(f"secret {name} must come from a file (no environment, content or external)")
        if secret.get("name") and not str(secret["name"]).startswith(env.volume_prefix):
            fail(f"secret {name} has a foreign name")
        path = str(secret["file"])
        parts = path.replace("\\", "/").split("/")
        if ".." in parts or parts[-1] != name:
            fail(f"secret {name} file must be named {name}")
        if env.name == "dev":
            if parts[-3:-1] != [".secrets", "dev"]:
                fail(f"secret {name} must come from {DEV_SECRETS_DIR}/")
        else:
            if not path.startswith("/"):
                fail(f"secret {name} must come from the absolute staging secrets directory")
            try:
                check_secrets_dir_value(os.path.dirname(path))
            except IsolationError as exc:
                fail(f"secret {name}: {exc}")


# ---------- Static rendering (tests and preflight without Docker) ----------

_VARIABLE = re.compile(r"\$\$|\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?)([-?])([^}]*))?\}")


def interpolate(value, variables: dict[str, str]):
    """Compose-style ${VAR}, ${VAR:-default}, ${VAR-default}, ${VAR:?msg}, ${VAR?msg}, $$."""
    if isinstance(value, dict):
        return {k: interpolate(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate(v, variables) for v in value]
    if not isinstance(value, str):
        return value

    def replace(match):
        if match.group(0) == "$$":
            return "$"
        key, colon, op, arg = match.groups()
        present = key in variables and (variables[key] != "" or not colon)
        if op == "?" and not present:
            raise IsolationError(f"Required variable {key} is not set")
        if op == "-" and not present:
            return arg
        return variables.get(key, "")

    return _VARIABLE.sub(replace, value)


def _merge(base, overlay):
    if isinstance(base, dict) and isinstance(overlay, dict):
        merged = dict(base)
        for key, value in overlay.items():
            merged[key] = _merge(base[key], value) if key in base else value
        return merged
    if isinstance(base, list) and isinstance(overlay, list):
        return base + [item for item in overlay if item not in base]
    return overlay


def static_config(env: Environment, variables: dict[str, str], *, root=ROOT, extra=()):
    """Approximate `docker compose config` for these files; needs PyYAML (tests only)."""
    import yaml  # noqa: PLC0415 - optional, test-time dependency

    merged: dict = {}
    for filename in env.files + tuple(extra):
        document = yaml.safe_load((Path(root) / filename).read_text()) or {}
        document = {k: v for k, v in document.items() if not k.startswith("x-")}
        merged = _merge(merged, interpolate(document, variables))
    return merged
