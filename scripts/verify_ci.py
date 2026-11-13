"""Run CI in a fresh synthetic-only stack; never target development containers.

The stack uses the same three-role, file-secret and guard architecture as
dev/staging. Every run gets:

* a random project ``nextup-ci-<12 hex>`` (containers, networks; no named volumes);
* migrations only through the guard: ``migrate plan-apply`` plans (read-only), shows the
  plan and a one-time confirmation code, and applies only after this launcher confirms the
  INIT plan on stdin. The single-use token never leaves the guard process.
  This runs before any runtime service starts; no service runs or waits for migrations.

Hardening:

* The launcher refuses to run with effective UID 0, before any Docker operation.
* One fresh run directory per run under an approved CI scratch root (default
  ``<system temp>/nextup-ci-<uid>``, or ``NEXTUP_CI_SCRATCH_ROOT``), outside the repository,
  outside any git working tree and outside every protected path of the optional private
  list. It holds ``secrets/`` (synthetic secret files) and ``e2e/`` (the only host directory
  a container may write). Before *every* subprocess, ``preflight()`` re-verifies owner,
  mode, file type, symlink-free paths, the inode recorded at creation (substitution), and
  each secret's presence and format, reporting file names only. The launcher root itself
  must not overlap a protected path (``check_root``): use a checkout outside every such path.
* CI runs in fixture data mode: synthetic fixtures, live fetching off, no provider
  credentials at all.

The run's synthetic secret values are registered with ``secret_audit``
in memory only (the migration token never reaches the launcher; the audit also scans every
source for the token format). ``finish()`` scans the evidence, the e2e output, the
launcher's own console, full Compose logs and the run's own container metadata *before*
any secret is deleted, rescans after cleanup, writes counts only (``secret_audit.json``)
and fails the run on any disclosure, anomaly or unscanned source.

Privileged checks (lint, ``alembic check``, the pytest suites) run in the ``tests`` service,
which holds the owner credential and the migration key; ``api``, ``worker`` and ``scheduler``
hold only the runtime credential. Tokens are masked in saved logs.
"""

import json
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from uuid import uuid4

import guard_session
import oss_env
import secret_audit
from check_config import check_services
from dependency_inventory import inventory
from verify_failures import main as verify_outages
from verify_recovery import verify_recovery

ROOT = Path(__file__).resolve().parents[1]
APPROVAL_VARIABLE = "NEXTUP_INTEGRATION_APPROVED"
SCRATCH_VARIABLE = "NEXTUP_CI_SCRATCH_ROOT"
LAUNCHER_VARIABLES = (APPROVAL_VARIABLE, SCRATCH_VARIABLE, oss_env.PROTECTED_FILE_VARIABLE)
REFUSAL_EXIT = 3
CI_PROJECT = re.compile(r"^nextup-ci-[0-9a-f]{12}$")
GUARD_PREFIX = "nextup-guard: "
TOKEN_LINE = re.compile(r"(nextup-guard: token=)\S+")

# Database identity is fixed for every CI run; only the Compose project is random.
CI_DATABASE = "nextup_ci"
CI_CLUSTER = "nextup-ci"
SECRET_NAMES = ("db_admin_password", "db_owner_password", "db_app_password", "migration_key")
SECRET_VALUE = re.compile(r"^[A-Za-z0-9_-]{24,256}$")
MAX_SECRET_BYTES = 4096
E2E_TARGET = "/app/test-results"
INIT_TARGET = "/docker-entrypoint-initdb.d"
RUNTIME_SERVICES = ("api", "worker", "scheduler")
# Services whose process user is the launcher's UID:GID (never root).
CI_USER_SERVICES = (*RUNTIME_SERVICES, "migrate", "tests", "e2e")
SERVICE_SECRETS = {
    "postgres": {"db_admin_password", "db_owner_password", "db_app_password"},
    "migrate": {"db_owner_password", "migration_key"},
    "tests": {"db_owner_password", "db_app_password", "migration_key"},
    **{name: {"db_app_password"} for name in RUNTIME_SERVICES},
}
INTERNAL_ONLY = {"postgres", "redis", "worker", "scheduler", "migrate", "tests"}
LEGACY_NAMES = frozenset(
    {
        "DATABASE_URL",
        "POSTGRES_PASSWORD",
        "PGPASSWORD",
        "PGOPTIONS",
        "REDIS_URL",
        "GMAIL_REFRESH_TOKEN",
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "ADZUNA_APP_ID",
        "ADZUNA_APP_KEY",
        "LIVE_JOB_FETCH_ENABLED",
        "FIXTURE_FETCH_ENABLED",
        "NEXTUP_FIXTURE_FETCH_ENABLED",
    }
)
DISABLED_INTEGRATIONS = (
    "NEXTUP_GMAIL_SYNC_ENABLED",
    "NEXTUP_CALENDAR_SYNC_ENABLED",
    "NEXTUP_EXTERNAL_CLASSIFIER_ENABLED",
)
# Fixture data mode: no provider credential, board or live switch may reach a CI container.
PROVIDER_KEYS = re.compile(r"ADZUNA|GREENHOUSE|GOOGLE|GMAIL_REFRESH")


class CIRefused(RuntimeError):
    """A CI precondition failed. Messages carry identifiers only, never secret contents."""


def require_integration_approval(environ):
    """Real containers, migrations and integration tests need an explicit opt-in."""
    if environ.get(APPROVAL_VARIABLE) != "1":
        raise PermissionError(
            f"Refused: this starts a disposable Docker stack, runs migrations and "
            f"integration tests. Set {APPROVAL_VARIABLE}=1 to confirm this one run."
        )


def shown(path):
    """A path as it may be printed into evidence: relative to the repository, never absolute."""
    try:
        return Path(path).relative_to(ROOT).as_posix()
    except ValueError:
        return Path(path).name


def refuse_root():
    """Never run the launcher (and so never start Docker work) as root."""
    if os.geteuid() == 0:
        raise CIRefused("Refused: the CI launcher must not run with effective UID 0")


def refuse_client_variables(environ):
    """PostgreSQL client variables never come from the launcher's shell. No CI
    process needs one: every connection is built from the stack's own NEXTUP_ settings."""
    found = oss_env.libpq_names(environ, server=True)
    if found:
        raise CIRefused(
            "Refused: PostgreSQL client variables in the shell (unset them): " + ", ".join(found)
        )


# ---------- path boundaries ----------


def protected_paths(environ):
    """Absolute paths from the optional private protected-resource list (never in code)."""
    return oss_env.load_protected(environ.get(oss_env.PROTECTED_FILE_VARIABLE))["paths"]


def _inside(path, root):
    path, root = os.path.normpath(str(path)), os.path.normpath(str(root))
    return path == root or path.startswith(root.rstrip("/") + "/")


def check_boundaries(path, label, protected=frozenset()):
    """Absolute, normalized, symlink-free; outside the repository, any git working tree and
    every protected path."""
    text = str(path)
    if not os.path.isabs(text) or os.path.normpath(text) != text or ".." in text.split("/"):
        raise CIRefused(f"Refused: {label} must be an absolute path without traversal")
    if os.path.realpath(text) != text:
        raise CIRefused(f"Refused: {label} must not contain symlinks")
    for root in (ROOT, *protected):
        resolved = os.path.realpath(str(root))
        if _inside(text, resolved) or _inside(resolved, text):
            raise CIRefused(f"Refused: {label} overlaps the repository or a protected path")
    for ancestor in (Path(text), *Path(text).parents):
        if (ancestor / ".git").exists():
            raise CIRefused(f"Refused: {label} is inside a git working tree")


def check_root(protected=frozenset()):
    """The launcher writes evidence under ROOT and bind-mounts ROOT's init scripts, so it must
    never run from (or around) a protected tree: use a checkout outside every such path."""
    root = os.path.realpath(str(ROOT))
    for path in protected:
        resolved = os.path.realpath(str(path))
        if _inside(root, resolved) or _inside(resolved, root):
            raise CIRefused(
                "Refused: the launcher root overlaps a protected path; "
                "run from a checkout outside every protected path"
            )


def check_private_dir(path, label, uid):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        raise CIRefused(f"Refused: {label} is missing") from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise CIRefused(f"Refused: {label} is not a real directory")
    if info.st_uid != uid or stat.S_IMODE(info.st_mode) != 0o700:
        raise CIRefused(f"Refused: {label} must be owned by the CI user with mode 0700")
    return info


def scratch_root(environ, uid, protected=frozenset()):
    """The approved CI scratch root: NEXTUP_CI_SCRATCH_ROOT, or <system temp>/nextup-ci-<uid>."""
    raw = environ.get(SCRATCH_VARIABLE)
    if raw:
        root = Path(raw)
    else:
        root = Path(os.path.realpath(tempfile.gettempdir())) / f"nextup-ci-{uid}"
    if not root.is_absolute():
        raise CIRefused(f"Refused: {SCRATCH_VARIABLE} must be an absolute path")
    check_boundaries(root, "CI scratch root", protected)  # before anything is created
    if not root.exists() and not root.is_symlink():
        root.mkdir(mode=0o700)
    check_boundaries(root, "CI scratch root", protected)
    check_private_dir(root, "CI scratch root", uid)
    return root


def _identity(info):
    return (info.st_dev, info.st_ino)


def write_synthetic_secrets(directory, audit=None):
    """Fresh random values for this run only; never printed, never copied from anywhere.
    Returns each file's (device, inode) so later substitution is detected. With an
    ``audit``, each value is also registered (memory only) for the disclosure audit."""
    values, identities = set(), {}
    for name in SECRET_NAMES:
        value = secrets.token_urlsafe(32)
        values.add(value)
        if audit is not None:
            audit.add(name, value)
        path = Path(directory) / name
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as output:
            output.write(value + "\n")
        identities[name] = _identity(os.lstat(path))
    assert len(values) == len(SECRET_NAMES)
    return identities


def check_secret_files(directory, uid, identities=None):
    """Every required secret exists as a regular, single-link, 0600 file owned by the CI
    user (the backends run as that UID:GID; postgres copies them as root), of the expected
    format, distinct, and (when recorded) the very file this run created. Names only."""
    present = sorted(os.listdir(directory))
    missing = sorted(set(SECRET_NAMES) - set(present))
    unexpected = sorted(set(present) - set(SECRET_NAMES))
    if missing or unexpected:
        raise CIRefused(
            "Refused: CI secrets directory content is wrong"
            + (f"; missing: {', '.join(missing)}" if missing else "")
            + (f"; unexpected entries: {len(unexpected)}" if unexpected else "")
        )
    values = set()
    for name in SECRET_NAMES:
        path = Path(directory) / name
        info = os.lstat(path)

        def fail(reason, name=name):
            raise CIRefused(f"Refused: CI secret file {name}: {reason}")

        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            fail("not a regular file")
        if info.st_nlink != 1:
            fail("has additional hard links")
        if info.st_uid != uid or stat.S_IMODE(info.st_mode) != 0o600:
            fail("must be owned by the CI user with mode 0600")
        if not 0 < info.st_size <= MAX_SECRET_BYTES:
            fail("has an invalid size")
        if identities is not None and identities.get(name) != _identity(info):
            fail("was replaced after this run created it")
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            fail("is not readable by the CI user")
        with os.fdopen(descriptor, "rb") as handle:
            if _identity(os.fstat(handle.fileno())) != _identity(info):
                fail("changed while being checked")
            data = handle.read(MAX_SECRET_BYTES + 1)
        text = data.decode("ascii", errors="replace")
        text = text[:-1] if text.endswith("\n") else text
        if not SECRET_VALUE.fullmatch(text):
            fail("does not have the expected format")
        values.add(text)
    if len(values) != len(SECRET_NAMES):
        raise CIRefused("Refused: CI secret files must all be distinct")


def _secrets_of(service):
    result = {}
    for item in service.get("secrets") or []:
        if isinstance(item, dict):
            result[str(item["source"])] = str(
                item.get("target") or f"/run/secrets/{item['source']}"
            )
        else:
            result[str(item)] = f"/run/secrets/{item}"
    return result


def _as_list(value):
    if value is None:
        return []
    return value.split() if isinstance(value, str) else [str(v) for v in value]


def _user_ok(value, expected=None):
    match = re.fullmatch(r"(\d+):(\d+)", str(value or ""))
    if not match or 0 in (int(match.group(1)), int(match.group(2))):
        return False
    return expected is None or str(value) == expected


def _in_run_dir(path, leaf, project):
    """Layout: <scratch root>/<project>-<random>/<leaf>, as Stack creates it."""
    path = Path(str(path))
    return (
        path.name == leaf
        and path.parent.name.startswith(f"{project}-")
        and (len(path.parent.name) > len(project) + 1)
    )


def validate_ci(config, secrets_dir=None, e2e_dir=None, expected_user=None):
    """The disposable CI contract (rendered `docker compose config --format json`)."""
    assert CI_PROJECT.fullmatch(str(config.get("name", ""))), (
        "Random nextup-ci-<12 hex> project required"
    )
    services = config["services"]
    check_services(services)
    assert not config.get("volumes"), "CI must not create named volumes"
    networks = config.get("networks") or {}
    assert all(not network.get("external") for network in networks.values()), "External network"
    assert (networks.get("backend") or {}).get("internal"), "CI backend network must be internal"
    init_source = os.path.normpath(str(ROOT / "backend/docker/initdb"))

    for name, service in services.items():
        for mount in service.get("volumes", []) or []:
            source = str(mount.get("source", ""))
            if name == "e2e" and mount.get("target") == E2E_TARGET:
                # Only this run's e2e directory, outside the repository.
                allowed = (
                    os.path.isabs(source)
                    and os.path.normpath(source) == source
                    and ".." not in source.split("/")
                    and not _inside(source, ROOT)
                    and _in_run_dir(source, "e2e", config["name"])
                    and (e2e_dir is None or source == str(e2e_dir))
                )
            elif name == "postgres" and mount.get("target") == INIT_TARGET:
                allowed = bool(mount.get("read_only")) and os.path.normpath(source) == init_source
            else:
                allowed = False
            assert mount["type"] == "bind" and allowed, f"Persistent or unexpected mount in {name}"
        mounted = _secrets_of(service)
        assert set(mounted) == SERVICE_SECRETS.get(name, set()), f"Unexpected secrets in {name}"
        assert all(t == f"/run/secrets/{s}" for s, t in mounted.items()), f"Secret path in {name}"
        env = service.get("environment") or {}
        client = oss_env.libpq_names(env, server=name == "postgres")
        assert not client, f"PostgreSQL client variable in {name}: " + ", ".join(client)
        for key in env:
            assert key not in LEGACY_NAMES and "N8N" not in key, f"Legacy variable in {name}"
            inline = key.endswith(("PASSWORD", "SECRET", "KEY", "TOKEN"))
            assert not inline or key.endswith("_FILE"), f"Inline credential variable in {name}"
            assert not PROVIDER_KEYS.search(key), f"Provider setting in {name}"
        for port in service.get("ports", []) or []:
            assert port["published"] == "0", "CI must allocate independent host ports"
            assert port.get("host_ip") == "127.0.0.1", "CI ports must be loopback-only"
        if name in INTERNAL_ONLY:
            assert set(service.get("networks") or {}) == {"backend"}, f"{name} must have no egress"
        for dependency in service.get("depends_on") or {}:
            assert dependency not in ("migrate", "tests"), f"{name} waits for {dependency}"
        if name in CI_USER_SERVICES:
            # Never root inside the CI backends, tests or e2e.
            assert _user_ok(service.get("user"), expected_user), f"{name} must run as the CI user"

    for name in RUNTIME_SERVICES:
        env = services[name]["environment"]
        assert env.get("NEXTUP_ENV") == "ci"
        assert env.get("NEXTUP_DB_USER") == f"{CI_DATABASE}_app"
        assert env.get("NEXTUP_DB_NAME") == CI_DATABASE and env.get("NEXTUP_DB_HOST") == "postgres"
        assert env.get("NEXTUP_DB_PASSWORD_FILE") == "/run/secrets/db_app_password"
        assert "NEXTUP_DB_ROLE" not in env and not any(
            k.startswith("NEXTUP_MIGRATION") for k in env
        )
        assert not services[name].get("entrypoint"), f"{name} must keep the guard entrypoint"
    for name in (*RUNTIME_SERVICES, "tests"):
        env = services[name]["environment"]
        # Synthetic fixtures only; live fetching off.
        assert env.get("NEXTUP_FIXTURE_DATA_MODE") == "true", "CI serves fixture data only"
        assert env.get("NEXTUP_LIVE_JOB_FETCH_ENABLED") == "false", "CI must not fetch live jobs"
    for name in (*RUNTIME_SERVICES, "migrate", "tests"):
        env = services[name]["environment"]
        assert env.get("NEXTUP_REDIS_URL") == "redis://redis:6379/0"
        assert all(env.get(flag) == "false" for flag in DISABLED_INTEGRATIONS), (
            f"{name} integration"
        )

    migrate = services["migrate"]
    assert migrate.get("profiles") == ["migrate"]
    assert _as_list(migrate.get("entrypoint")) == ["python", "-m", "app.guard"]
    assert _as_list(migrate.get("command")) == ["plan"]
    assert migrate["environment"].get("NEXTUP_ENV") == "ci"
    assert migrate["environment"].get("NEXTUP_DB_ROLE") == "migrator"
    assert migrate["environment"].get("NEXTUP_DB_USER") == f"{CI_DATABASE}_owner"
    tests = services["tests"]
    assert tests.get("profiles") == ["test"]
    assert _as_list(tests.get("entrypoint")) == ["/usr/bin/env"], "tests must not serve"
    assert tests["environment"].get("NEXTUP_ENV") == "test"
    assert tests["environment"].get("NEXTUP_DB_ROLE") == "migrator"
    assert tests["environment"].get("NEXTUP_DB_USER") == f"{CI_DATABASE}_owner"
    assert not migrate.get("ports") and not tests.get("ports")

    postgres = services["postgres"]
    assert postgres["environment"] == {
        "POSTGRES_USER": f"{CI_DATABASE}_admin",
        "POSTGRES_DB": "postgres",
        "POSTGRES_PASSWORD_FILE": "/run/secrets/db_admin_password",
        "PGDATA": "/var/lib/postgresql/ci-data",
    }
    assert _as_list(postgres.get("command")) == ["postgres", "-c", f"cluster_name={CI_CLUSTER}"]
    assert any(str(t).startswith("/run/nextup-initdb") for t in postgres.get("tmpfs") or [])
    assert postgres.get("tmpfs") and services["redis"].get("tmpfs")
    assert services["scheduler"].get("tmpfs")

    top = config.get("secrets") or {}
    assert set(top) == set(SECRET_NAMES), "CI secrets must be exactly the synthetic set"
    for name, secret in top.items():
        assert set(secret) <= {"file", "name"} and secret.get("file"), f"{name} must be file-based"
        path = Path(str(secret["file"]))
        assert path.is_absolute() and path.name == name
        assert ROOT.resolve() not in path.resolve().parents, (
            "CI secrets must live outside the repository"
        )
        assert _in_run_dir(path.parent, "secrets", config["name"]), (
            "CI secrets must come from a launcher run directory"
        )
        if secrets_dir is not None:
            assert path.parent == Path(secrets_dir), (
                "CI secrets must come from this run's directory"
            )


class Stack:
    def __init__(self):
        refuse_root()
        self.project = f"nextup-ci-{uuid4().hex[:12]}"
        self.uid, self.gid = os.getuid(), os.getgid()
        self.expected_user = f"{self.uid}:{self.gid}"
        self.protected = protected_paths(os.environ)
        check_root(self.protected)  # before anything is written under ROOT
        self.artifacts = ROOT / "test-results" / "ci" / self.project
        (self.artifacts / "browser").mkdir(parents=True)
        (self.artifacts / "backend").mkdir(parents=True)
        # One fresh private run directory under the approved scratch root: outside
        # the repository and the uploaded evidence; removed in finish().
        self.scratch_root = scratch_root(os.environ, self.uid, self.protected)
        self.run_dir = Path(tempfile.mkdtemp(prefix=f"{self.project}-", dir=self.scratch_root))
        self.secrets_dir = self.run_dir / "secrets"
        self.e2e_dir = self.run_dir / "e2e"
        self.secrets_dir.mkdir(mode=0o700)
        self.e2e_dir.mkdir(mode=0o700)
        self.dir_identities = {
            path: _identity(os.lstat(path))
            for path in (self.run_dir, self.secrets_dir, self.e2e_dir)
        }
        self.audit = secret_audit.SecretAudit()
        self.secret_identities = write_synthetic_secrets(self.secrets_dir, self.audit)
        # Only an allowlist of host variables reaches Compose and the checks: the tools'
        # own variables and this launcher's three. Nothing else from the shell is forwarded.
        self.env = oss_env.child_environment(os.environ)
        self.env.update((key, os.environ[key]) for key in LAUNCHER_VARIABLES if key in os.environ)
        self.env.update(
            NEXTUP_CI_E2E_DIR=str(self.e2e_dir),
            NEXTUP_CI_SECRETS_DIR=str(self.secrets_dir),
            NEXTUP_CI_UID=str(self.uid),
            NEXTUP_CI_GID=str(self.gid),
        )
        self.preflight()
        self.command = [
            "docker",
            "compose",
            "--project-name",
            self.project,
            "--env-file",
            str(ROOT / ".env.example"),
            "-f",
            str(ROOT / "compose.ci.yaml"),
        ]
        self.results = []

    def preflight(self):
        """Before every subprocess: root refusal, run-directory boundaries and
        identity, and every secret file. Raises CIRefused naming paths/files only."""
        refuse_root()
        check_root(self.protected)
        check_boundaries(self.scratch_root, "CI scratch root", self.protected)
        check_private_dir(self.scratch_root, "CI scratch root", self.uid)
        for path, label in (
            (self.run_dir, "CI run directory"),
            (self.secrets_dir, "CI secrets directory"),
            (self.e2e_dir, "CI e2e output directory"),
        ):
            check_boundaries(path, label, self.protected)
            if not _inside(path, self.scratch_root):
                raise CIRefused(f"Refused: {label} is outside the CI scratch root")
            info = check_private_dir(path, label, self.uid)
            if _identity(info) != self.dir_identities[path]:
                raise CIRefused(f"Refused: {label} was replaced after this run created it")
        if (self.env.get("NEXTUP_CI_E2E_DIR"), self.env.get("NEXTUP_CI_SECRETS_DIR")) != (
            str(self.e2e_dir),
            str(self.secrets_dir),
        ):
            raise CIRefused("Refused: CI directory variables do not match this run")
        if self.env.get("NEXTUP_CI_UID") != str(self.uid) or self.env.get("NEXTUP_CI_GID") != str(
            self.gid
        ):
            raise CIRefused("Refused: CI user variables do not match the launcher user")
        check_secret_files(self.secrets_dir, self.uid, self.secret_identities)

    def compose(self, *args):
        self.preflight()
        return subprocess.run(
            self.command + list(args),
            cwd=ROOT,
            env=self.env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def compose_result(self, *args, timeout=300):
        """Like compose(), but returns the completed process even when it fails."""
        self.preflight()
        return subprocess.run(
            self.command + list(args),
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def docker_read(self, args):
        """Audit only: read-only engine queries scoped to this run (secret_audit allowlist)."""
        if not secret_audit.allowed_engine_command(self.project, args):
            raise PermissionError("engine command outside the audit allowlist")
        self.preflight()
        result = subprocess.run(
            ["docker", *args], cwd=ROOT, env=self.env, capture_output=True, timeout=120
        )
        return result.returncode, result.stdout

    @contextmanager
    def console(self):
        """Tee the launcher's own output into the evidence, so the disclosure audit scans it too."""
        path = self.artifacts / "console.log"
        with path.open("w") as log:

            class Tee:
                def __init__(self, stream):
                    self.stream = stream

                def write(self, text):
                    log.write(text)
                    return self.stream.write(text)

                def flush(self):
                    log.flush()
                    self.stream.flush()

            with redirect_stdout(Tee(sys.stdout)), redirect_stderr(Tee(sys.stderr)):
                yield

    def run_secret_audit(self, stage):
        """Disclosure-audit scan; never raises, so cleanup always continues."""
        audit = getattr(self, "audit", None)
        if audit is None:
            return
        sys.stdout.flush()  # the console tee writes through to console.log
        sys.stderr.flush()
        if stage == "before-cleanup":
            try:
                secret_audit.collect_engine(
                    audit,
                    self.project,
                    self.docker_read,
                    lambda: self.compose("logs", "--no-color"),
                )
            except (Exception, KeyboardInterrupt) as exc:  # noqa: BLE001 - recorded, run fails
                audit.source_failed("engine", type(exc).__name__)
        sources = [("evidence", self.artifacts)]
        if stage == "before-cleanup":
            sources.append(("e2e", self.e2e_dir))
        for label, root in sources:
            try:
                audit.scan_tree(label, root)
            except (Exception, KeyboardInterrupt) as exc:  # noqa: BLE001
                audit.source_failed(label, type(exc).__name__)

    def step(self, name, command, timeout=900, input_text=None):
        self.preflight()
        print(f"RUN: {name}", flush=True)
        path = self.artifacts / f"{name}.log"
        with path.open("w") as output:
            try:
                result = subprocess.run(
                    command,
                    cwd=ROOT,
                    env=self.env,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                    input=None if input_text is None else input_text.encode(),
                )
                code = result.returncode
            except subprocess.TimeoutExpired:
                code = 124
                output.write("\nCHECK TIMED OUT\n")
        self.results.append({"check": name, "exit_code": code})
        print(path.read_text()[-6000:], flush=True)
        if code:
            raise RuntimeError(f"{name} failed ({code}); see {shown(path)}")
        print(f"PASS: {name}", flush=True)

    def check(self, name, *args, timeout=900, input_text=None):
        self.step(name, self.command + list(args), timeout=timeout, input_text=input_text)

    def tests(self, name, *command, timeout=900, integration=False):
        """Run a command in a fresh `tests` container (profile test, no dependencies)."""
        extra = ["-e", "RUN_INTEGRATION=1"] if integration else []
        self.check(
            name,
            "--profile",
            "test",
            "run",
            "--rm",
            "--no-deps",
            *extra,
            "--volume",
            f"{self.artifacts / 'backend'}:/ci-results",
            "tests",
            *command,
            timeout=timeout,
        )

    def migrate(self):
        """Guarded INIT of the fresh CI database through ``guard plan-apply``: the guard plans
        (read-only), shows the plan and a one-time confirmation code, and applies only after
        that code arrives on stdin. The authorization token never leaves the guard process,
        so it cannot reach an argument, variable, log or this launcher."""
        self.preflight()
        print("RUN: migration", flush=True)
        command = self.command + [
            "--profile",
            "migrate",
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "migrate",
            "plan-apply",
        ]

        def decide(lines, code):
            # Only the expected first migration of a fresh database is ever confirmed.
            return code if any(GUARD_PREFIX + "PLAN mode=INIT " in line for line in lines) else None

        session = guard_session.plan_apply(
            command, decide=decide, cwd=ROOT, env=self.env, timeout=1800
        )
        text = "\n".join(session.lines) + "\n"
        (self.artifacts / "migration.log").write_text(TOKEN_LINE.sub(r"\1<masked>", text))
        applied = (
            session.confirmed
            and session.returncode == 0
            and any(line.startswith(GUARD_PREFIX + "APPLIED mode=INIT ") for line in session.lines)
        )
        self.results.append({"check": "migration", "exit_code": 0 if applied else 1})
        if not applied:
            raise RuntimeError(
                "migration did not plan, confirm and apply INIT on the fresh CI database"
            )

    def request(self, path, method="GET", body=None):
        address = self.compose("port", "api", "8000")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"http://{address}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

    def seed(self):
        assert self.project.startswith("nextup-ci-")
        assert self.request("/api/profile")[0] == 404, "Refusing to overwrite a profile"
        fixture = json.loads((ROOT / "backend/tests/fixtures/profile.synthetic.json").read_text())
        code, result = self.request("/api/profile", "PUT", fixture)
        assert code == 200 and result == fixture
        assert self.request("/api/discovery", "PUT", {"enabled": False, "boards": []})[0] == 200
        self.results.append({"check": "synthetic-profile", "exit_code": 0})

    def exercise(self, name, action):
        path = self.artifacts / f"{name}.log"
        try:
            with path.open("w") as output, redirect_stdout(output):
                action()
        finally:
            print(path.read_text(), flush=True)
        self.results.append({"check": name, "exit_code": 0})

    def finish(self):
        # A preflight refusal here (tampered run directory or secrets) skips every engine
        # operation and is recorded as a cleanup failure; nothing is run against Docker.
        errors = []
        for name, args in {
            "services.log": ["ps", "--all"],
            "compose.log": ["logs", "--no-color", "--tail=300"],
        }.items():
            try:
                (self.artifacts / name).write_text(
                    TOKEN_LINE.sub(r"\1<masked>", self.compose(*args))
                )
            except (subprocess.SubprocessError, CIRefused):
                errors.append(name)
        # May not exist if a prior prerequisite/build check failed.
        for source, target, check in [
            ("api:/tmp/stack.xml", "stack.xml", "stack-tests"),
            ("frontend:/tmp/frontend.xml", "frontend.xml", "frontend-tests"),
        ]:
            try:
                self.compose("cp", source, str(self.artifacts / target))
            except (subprocess.SubprocessError, CIRefused):
                if any(result["check"] == check for result in self.results):
                    errors.append(target)
        for target, check in (
            ("migrations.xml", "migration-roundtrips"),
            ("backend.xml", "backend-tests"),
        ):
            ran = any(result["check"] == check for result in self.results)
            if ran and not (self.artifacts / "backend" / target).is_file():
                errors.append(target)
        if any(result["check"] == "browser-tests" for result in self.results):
            # Copy only a regular file out of this run's e2e directory (never follow links).
            source = self.e2e_dir / "browser.xml"
            try:
                info = os.lstat(source)
                if not stat.S_ISREG(info.st_mode) or info.st_size > 50_000_000:
                    raise OSError("unexpected e2e result file")
                shutil.copyfile(
                    source, self.artifacts / "browser/browser.xml", follow_symlinks=False
                )
            except OSError:
                errors.append("browser.xml")
        # Scan before any secret or container is removed.
        self.run_secret_audit("before-cleanup")
        try:
            self.compose("down", "--timeout", "10")  # No volume removal, ever.
            if self.compose("ps", "--all", "--quiet"):
                errors.append("cleanup")
        except (subprocess.SubprocessError, CIRefused):
            errors.append("cleanup")
        try:
            shutil.rmtree(self.run_dir)  # secrets and e2e output of this run only
        except OSError:
            errors.append("secrets-cleanup")
        print(f"Evidence: {shown(self.artifacts)}", flush=True)
        audit = getattr(self, "audit", None)
        if audit is None:
            report = {"passed": False, "complete": False, "reason": "audit not configured"}
        else:
            self.run_secret_audit("after-cleanup")  # anything written during cleanup
            report = audit.report()
            audit.clear()
        if not report.get("passed"):
            errors.append("secret-audit")
        (self.artifacts / "secret_audit.json").write_text(json.dumps(report, indent=2) + "\n")
        (self.artifacts / "summary.json").write_text(
            json.dumps(
                {
                    "project": self.project,
                    "checks": self.results,
                    "collection_errors": errors,
                    "cleanup_passed": "cleanup" not in errors and "secrets-cleanup" not in errors,
                    "secret_audit": {
                        k: report.get(k) for k in ("passed", "complete", "disclosures")
                    },
                    "passed": not errors
                    and all(result["exit_code"] == 0 for result in self.results),
                },
                indent=2,
            )
            + "\n"
        )
        return not errors


def main(environ=None):
    try:
        require_integration_approval(os.environ if environ is None else environ)
    except PermissionError as exc:
        print(exc, file=sys.stderr, flush=True)
        return REFUSAL_EXIT
    try:
        refuse_root()  # before creating anything or touching Docker
        refuse_client_variables(os.environ if environ is None else environ)
        stack = Stack()  # creates the run directory and runs the first preflight
    except CIRefused as exc:
        print(exc, file=sys.stderr, flush=True)
        return REFUSAL_EXIT

    def interrupted(signum, frame):
        raise KeyboardInterrupt(f"Interrupted by signal {signum}")

    signal.signal(signal.SIGTERM, interrupted)
    with stack.console():
        return _run(stack)


def _run(stack):
    success = False
    try:
        config = json.loads(
            stack.compose("--profile", "test", "--profile", "migrate", "config", "--format", "json")
        )
        assert config["name"] == stack.project
        validate_ci(config, stack.secrets_dir, stack.e2e_dir, stack.expected_user)
        stack.step(
            "development-config", [sys.executable, "scripts/check_config.py", "--example-env"]
        )
        stack.step(
            "workflow-lint",
            [
                "docker",
                "run",
                "--rm",
                "--network=none",
                "--mount",
                f"type=bind,src={ROOT / '.github/workflows'},dst=/work,readonly",
                "--workdir",
                "/work",
                "rhysd/actionlint:1.7.7@sha256:887a259a5a534f3c4f36cb02dca341673c6089431057242cdc931e9f133147e9",
                "ci.yml",
            ],
        )
        stack.step(
            "runner-tests",
            [sys.executable, "-m", "unittest", "discover", "-s", "scripts/tests", "-v"],
        )
        (stack.artifacts / "dependencies.json").write_text(json.dumps(inventory(), indent=2) + "\n")
        stack.results.append({"check": "lockfile-origins-hashes", "exit_code": 0})
        # Data services first; the schema exists only after an authorized INIT.
        stack.check(
            "data-services", "up", "--build", "--wait", "--wait-timeout", "180", "postgres", "redis"
        )
        stack.migrate()
        stack.check("startup", "up", "--build", "--wait", "--wait-timeout", "180")
        for check, args in (("runner-lint", ["check"]), ("runner-format", ["format", "--check"])):
            stack.check(
                check,
                "--profile",
                "test",
                "run",
                "--rm",
                "--no-deps",
                "--volume",
                f"{ROOT / 'scripts'}:/ci-scripts:ro",
                "tests",
                "ruff",
                *args,
                "--no-cache",
                "--config",
                "/app/pyproject.toml",
                "/ci-scripts",
            )
        stack.tests("backend-lint", "ruff", "check", "--no-cache", ".")
        stack.tests("backend-format", "ruff", "format", "--no-cache", "--check", ".")
        # --no-cache: the container runs as the launcher's UID, which may have no home
        # directory in the image, so uv's default cache location may not be writable.
        stack.tests("python-dependencies", "uv", "pip", "check", "--no-cache")
        # Read-only (READ ONLY transaction); the guard's own tables are excluded from compare.
        stack.tests("migration", "python", "-m", "alembic", "check")
        stack.tests(
            "migration-roundtrips",
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests/test_migrations_integration.py",
            "--junitxml=/ci-results/migrations.xml",
            integration=True,
        )
        # The synthetic profile gates fixture fetches through the real broker and worker.
        stack.seed()
        stack.tests(
            "backend-tests",
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--ignore=tests/test_migrations_integration.py",
            "--ignore=tests/test_integration.py",
            "--junitxml=/ci-results/backend.xml",
            integration=True,
        )
        # End-to-end checks against the running stack use the runtime credential only.
        stack.check(
            "stack-tests",
            "exec",
            "-T",
            "-e",
            "RUN_INTEGRATION=1",
            "api",
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests/test_integration.py",
            "--junitxml=/tmp/stack.xml",
        )
        stack.check("frontend-format", "exec", "-T", "frontend", "npm", "run", "format:check")
        stack.check("node-dependencies", "exec", "-T", "frontend", "npm", "ls", "--all")
        stack.check("frontend-build", "exec", "-T", "frontend", "npm", "run", "build")
        stack.check(
            "frontend-tests",
            "exec",
            "-T",
            "frontend",
            "npm",
            "test",
            "--",
            "--reporter=default",
            "--reporter=junit",
            "--outputFile=/tmp/frontend.xml",
        )
        # DML only, as the runtime role, after checking identity components.
        stack.check(
            "synthetic-retention-history",
            "exec",
            "-T",
            "api",
            "python",
            "-m",
            "tests.seed_retention_ci",
        )
        stack.check(
            "browser-tests",
            "--profile",
            "test",
            "run",
            "--build",
            "--rm",
            "--no-deps",
            "e2e",
            "npm",
            "run",
            "test:e2e",
            "--",
            "--reporter=list,junit",
        )
        stack.exercise(
            "service-outages",
            lambda: verify_outages(
                compose_fn=stack.compose, request_fn=stack.request, project=stack.project
            ),
        )
        stack.exercise("database-recovery", lambda: verify_recovery(stack))
        success = True
    except (Exception, KeyboardInterrupt) as exc:
        print(f"FAIL: {exc}", file=sys.stderr, flush=True)
        stack.results.append({"check": "run", "exit_code": 1, "error": type(exc).__name__})
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        cleaned = stack.finish()
    return 0 if success and cleaned else 1


if __name__ == "__main__":
    sys.exit(main())
