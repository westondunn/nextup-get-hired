"""Guard the isolated runner's CI contract, hardening, failure/cleanup
behaviour and guarded migration flow without starting any services."""

import copy
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guard_session
import oss_env
import secret_audit
import verify_ci
from dependency_inventory import inventory

try:
    import yaml
except ImportError:  # pragma: no cover - depends on the host interpreter
    yaml = None

REPO = Path(__file__).resolve().parents[2]
PROJECT = "nextup-ci-0123456789ab"
RUN_DIR = "/tmp/nextup-ci-1001/nextup-ci-0123456789ab-run"
SECRETS_DIR = f"{RUN_DIR}/secrets"
E2E_DIR = f"{RUN_DIR}/e2e"
USER = "1001:1001"
# A realistic token shape (prefix, payload, MAC); synthetic.
TOKEN = (
    "nxa1."
    + "eyJ2IjoxLCJub25jZSI6InN5bnRoZXRpYyJ9"
    + "QUFB" * 8
    + ".m4cS1gn4tur3Synth3t1cOnlyForUnitTestsXYZ012"
)


def _secrets(*names):
    return [{"source": n, "target": f"/run/secrets/{n}"} for n in names]


def config(project=PROJECT, secrets_dir=None, e2e_dir=None, user=USER):
    """The shape `docker compose config --format json` returns for a valid CI stack."""
    run_dir = f"/tmp/nextup-ci-1001/{project}-run"
    secrets_dir = secrets_dir or f"{run_dir}/secrets"
    e2e_dir = e2e_dir or f"{run_dir}/e2e"
    db = {
        "NEXTUP_DB_HOST": "postgres",
        "NEXTUP_DB_PORT": "5432",
        "NEXTUP_DB_NAME": "nextup_ci",
        "NEXTUP_REDIS_URL": "redis://redis:6379/0",
        "NEXTUP_GMAIL_SYNC_ENABLED": "false",
        "NEXTUP_CALENDAR_SYNC_ENABLED": "false",
        "NEXTUP_EXTERNAL_CLASSIFIER_ENABLED": "false",
    }
    features = {"NEXTUP_FIXTURE_DATA_MODE": "true", "NEXTUP_LIVE_JOB_FETCH_ENABLED": "false"}
    runtime_env = {
        **db,
        **features,
        "NEXTUP_ENV": "ci",
        "NEXTUP_DB_USER": "nextup_ci_app",
        "NEXTUP_DB_PASSWORD_FILE": "/run/secrets/db_app_password",
    }
    backend = {"user": user, "restart": "no", "networks": {"backend": None}}
    runtime = {
        **backend,
        "environment": runtime_env,
        "secrets": _secrets("db_app_password"),
        "depends_on": {
            "postgres": {"condition": "service_healthy"},
            "redis": {"condition": "service_healthy"},
        },
    }
    migrator = {
        **db,
        "NEXTUP_DB_ROLE": "migrator",
        "NEXTUP_DB_USER": "nextup_ci_owner",
        "NEXTUP_DB_PASSWORD_FILE": "/run/secrets/db_owner_password",
        "NEXTUP_MIGRATION_KEY_FILE": "/run/secrets/migration_key",
    }
    services = {
        "postgres": {
            "command": ["postgres", "-c", "cluster_name=nextup-ci"],
            "environment": {
                "POSTGRES_USER": "nextup_ci_admin",
                "POSTGRES_DB": "postgres",
                "POSTGRES_PASSWORD_FILE": "/run/secrets/db_admin_password",
                "PGDATA": "/var/lib/postgresql/ci-data",
            },
            "secrets": _secrets("db_admin_password", "db_owner_password", "db_app_password"),
            "tmpfs": [
                "/var/lib/postgresql/data:size=16777216",
                "/run/nextup-initdb:mode=0700,size=65536",
            ],
            "volumes": [
                {
                    "type": "bind",
                    "source": f"{REPO}/backend/docker/initdb",
                    "target": "/docker-entrypoint-initdb.d",
                    "read_only": True,
                }
            ],
            "networks": {"backend": None},
        },
        "redis": {"tmpfs": ["/data:size=67108864"], "networks": {"backend": None}},
        "migrate": {
            **backend,
            "profiles": ["migrate"],
            "entrypoint": ["python", "-m", "app.guard"],
            "command": ["plan"],
            "environment": {**migrator, "NEXTUP_ENV": "ci"},
            "secrets": _secrets("db_owner_password", "migration_key"),
            "depends_on": {"postgres": {"condition": "service_healthy"}},
        },
        "tests": {
            **backend,
            "profiles": ["test"],
            "entrypoint": ["/usr/bin/env"],
            "command": ["python", "-c", "print()"],
            "environment": {**migrator, **features, "NEXTUP_ENV": "test"},
            "secrets": _secrets("db_owner_password", "db_app_password", "migration_key"),
        },
        "api": {
            **runtime,
            "networks": {"backend": None, "edge": None},
            "ports": [{"host_ip": "127.0.0.1", "published": "0", "target": 8000}],
        },
        "worker": {**runtime, "command": ["celery", "worker"]},
        "scheduler": {**runtime, "command": ["celery", "beat"], "tmpfs": ["/state"]},
        "frontend": {
            "networks": {"edge": None},
            "ports": [{"host_ip": "127.0.0.1", "published": "0", "target": 5173}],
        },
        "e2e": {
            "profiles": ["test"],
            "user": user,
            "networks": {"edge": None},
            "volumes": [{"type": "bind", "source": e2e_dir, "target": "/app/test-results"}],
        },
    }
    secrets = {
        n: {"name": f"{project}_{n}", "file": f"{secrets_dir}/{n}"} for n in verify_ci.SECRET_NAMES
    }
    return {
        "name": project,
        "services": services,
        "networks": {
            "backend": {"name": f"{project}_backend", "internal": True},
            "edge": {"name": f"{project}_edge"},
        },
        "secrets": secrets,
    }


def _long_form(doc, variables, root=REPO):
    """Static approximation of `docker compose config` for compose.ci.yaml (tests only):
    interpolation, long-form ports/mounts/networks/secrets, sources resolved like Compose."""
    doc = oss_env.interpolate({k: v for k, v in doc.items() if not k.startswith("x-")}, variables)
    for service in doc["services"].values():
        ports = []
        for port in service.get("ports", []) or []:
            host_ip, published, target = str(port).split(":")
            ports.append({"host_ip": host_ip, "published": published, "target": int(target)})
        if ports:
            service["ports"] = ports
        mounts = []
        for mount in service.get("volumes", []) or []:
            parts = str(mount).split(":")
            source = (
                parts[0] if parts[0].startswith("/") else os.path.normpath(str(root / parts[0]))
            )
            mounts.append(
                {
                    "type": "bind",
                    "source": source,
                    "target": parts[1],
                    "read_only": len(parts) > 2 and parts[2] == "ro",
                }
            )
        if mounts:
            service["volumes"] = mounts
        if isinstance(service.get("networks"), list):
            service["networks"] = {n: None for n in service["networks"]}
        service["secrets"] = _secrets(*service.get("secrets", []))
        if not service["secrets"]:
            service.pop("secrets")
    return doc


def static_ci_render(project=PROJECT, extra=None, **variables):
    run_dir = f"/tmp/nextup-ci-1001/{project}-run"
    values = {
        "NEXTUP_CI_UID": "1001",
        "NEXTUP_CI_GID": "1001",
        "NEXTUP_CI_E2E_DIR": f"{run_dir}/e2e",
        "NEXTUP_CI_SECRETS_DIR": f"{run_dir}/secrets",
        **variables,
    }
    doc = yaml.safe_load((REPO / "compose.ci.yaml").read_text())
    if extra:
        doc = oss_env._merge(doc, extra)
    rendered = _long_form(copy.deepcopy(doc), {k: v for k, v in values.items() if v is not None})
    rendered["name"] = project
    return rendered


class ConfigGuards(unittest.TestCase):
    def test_safe_fixture_is_accepted(self):
        verify_ci.validate_ci(config())
        verify_ci.validate_ci(config(), SECRETS_DIR, E2E_DIR, USER)

    def test_random_projects_keep_one_database_guard_identity(self):
        for _ in range(3):
            stack_project = f"nextup-ci-{os.urandom(6).hex()}"
            value = config(project=stack_project)
            verify_ci.validate_ci(value)
            env = value["services"]["api"]["environment"]
            self.assertEqual(
                (env["NEXTUP_DB_NAME"], env["NEXTUP_DB_USER"]), ("nextup_ci", "nextup_ci_app")
            )
            self.assertEqual(value["services"]["postgres"]["command"][-1], "cluster_name=nextup-ci")

    def test_rejects_unsafe_mutations(self):
        s = "services"
        mutations = {
            "fixed project": lambda c: c.update(name="nextup-ci-test"),
            "protected-looking project": lambda c: c.update(name="other-stack"),
            "fixture mode off": lambda c: c[s]["api"]["environment"].update(
                NEXTUP_FIXTURE_DATA_MODE="false"
            ),
            "live fetching on": lambda c: c[s]["worker"]["environment"].update(
                NEXTUP_LIVE_JOB_FETCH_ENABLED="true"
            ),
            "retired fixture flag": lambda c: c[s]["worker"]["environment"].update(
                NEXTUP_FIXTURE_FETCH_ENABLED="true"
            ),
            "provider credential file": lambda c: c[s]["worker"]["environment"].update(
                NEXTUP_ADZUNA_APP_KEY_FILE="/run/secrets/adzuna_app_key"
            ),
            "provider board": lambda c: c[s]["api"]["environment"].update(
                NEXTUP_GREENHOUSE_COMPANY_NAME="Example"
            ),
            "named volume": lambda c: c.update(volumes={"postgres-data": {}}),
            "persistent mount": lambda c: c[s]["postgres"]["volumes"].append(
                {"type": "volume", "source": "data", "target": "/var/lib/postgresql/data"}
            ),
            "writable init scripts": lambda c: c[s]["postgres"]["volumes"][0].update(
                read_only=False
            ),
            "foreign init source": lambda c: c[s]["postgres"]["volumes"][0].update(
                source="/srv/initdb"
            ),
            "e2e source elsewhere": lambda c: c[s]["e2e"]["volumes"][0].update(source="/"),
            "e2e source relative": lambda c: c[s]["e2e"]["volumes"][0].update(source="e2e"),
            "e2e source traversal": lambda c: c[s]["e2e"]["volumes"][0].update(
                source=f"{RUN_DIR}/../../etc"
            ),
            "e2e source in repository": lambda c: c[s]["e2e"]["volumes"][0].update(
                source=str(REPO / "test-results")
            ),
            "e2e source of another project": lambda c: c[s]["e2e"]["volumes"][0].update(
                source="/tmp/nextup-ci-1001/nextup-ci-ffffffffffff-run/e2e"
            ),
            "secrets of another project": lambda c: c["secrets"]["migration_key"].update(
                file="/tmp/nextup-ci-1001/nextup-ci-ffffffffffff-run/secrets/migration_key"
            ),
            "secrets outside a run directory": lambda c: [
                c["secrets"][n].update(file=f"/srv/secrets/{n}") for n in verify_ci.SECRET_NAMES
            ],
            "e2e extra mount": lambda c: c[s]["e2e"]["volumes"].append(
                {"type": "bind", "source": E2E_DIR, "target": "/elsewhere"}
            ),
            "root CI user": lambda c: c[s]["api"].update(user="0:0"),
            "root group": lambda c: c[s]["tests"].update(user="1001:0"),
            "no CI user": lambda c: c[s]["worker"].pop("user"),
            "e2e as root": lambda c: c[s]["e2e"].update(user="0:0"),
            "all interfaces": lambda c: c[s]["api"]["ports"][0].update(host_ip="0.0.0.0"),
            "fixed host port": lambda c: c[s]["api"]["ports"][0].update(published="8000"),
            "published redis": lambda c: c[s]["redis"].update(
                ports=[{"host_ip": "127.0.0.1", "published": "0", "target": 6379}]
            ),
            "second scheduler": lambda c: c[s]["worker"].update(command=["celery", "beat"]),
            "external network": lambda c: c["networks"].update(default={"external": True}),
            "backend has egress": lambda c: c["networks"]["backend"].update(internal=False),
            "worker on edge": lambda c: c[s]["worker"]["networks"].update(edge=None),
            "tests on edge": lambda c: c[s]["tests"]["networks"].update(edge=None),
            "legacy DATABASE_URL": lambda c: c[s]["api"]["environment"].update(
                DATABASE_URL="postgresql+psycopg://nextup_ci:x@postgres:5432/nextup_ci"
            ),
            "PGOPTIONS in a runtime service": lambda c: c[s]["api"]["environment"].update(
                PGOPTIONS="-c nextup.provisioning=complete-v1"
            ),
            "PGOPTIONS in migrate": lambda c: c[s]["migrate"]["environment"].update(
                PGOPTIONS="-c nextup.provisioning=complete-v1"
            ),
            "PGOPTIONS in the test runner": lambda c: c[s]["tests"]["environment"].update(
                PGOPTIONS="-c nextup.provisioning=complete-v1"
            ),
            "PGOPTIONS in postgres": lambda c: c[s]["postgres"]["environment"].update(
                PGOPTIONS="-c nextup.provisioning=complete-v1"
            ),
            "PGHOSTADDR in the api": lambda c: c[s]["api"]["environment"].update(
                PGHOSTADDR="203.0.113.9"
            ),
            "PGSERVICE in the worker": lambda c: c[s]["worker"]["environment"].update(
                PGSERVICE="other"
            ),
            "PGSERVICEFILE in the scheduler": lambda c: c[s]["scheduler"]["environment"].update(
                PGSERVICEFILE="/tmp/pg_service.conf"
            ),
            "PGPORT in migrate": lambda c: c[s]["migrate"]["environment"].update(PGPORT="6543"),
            "PGSSLMODE in the api": lambda c: c[s]["api"]["environment"].update(
                PGSSLMODE="disable"
            ),
            "unknown client variable in the worker": lambda c: c[s]["worker"]["environment"].update(
                PGNEWTHING="x"
            ),
            "PGHOSTADDR in postgres": lambda c: c[s]["postgres"]["environment"].update(
                PGHOSTADDR="203.0.113.9"
            ),
            "PGPORT in postgres": lambda c: c[s]["postgres"]["environment"].update(PGPORT="6543"),
            "PGHOSTADDR in the test runner": lambda c: c[s]["tests"]["environment"].update(
                PGHOSTADDR="203.0.113.9"
            ),
            "PGSERVICE in the browser tests": lambda c: c[s]["e2e"].update(
                environment={"PGSERVICE": "other"}
            ),
            "inline password": lambda c: c[s]["worker"]["environment"].update(
                NEXTUP_DB_PASSWORD="p" * 30
            ),
            "inline token": lambda c: c[s]["api"]["environment"].update(
                NEXTUP_GMAIL_REFRESH_TOKEN="t"
            ),
            "gmail on": lambda c: c[s]["worker"]["environment"].update(
                NEXTUP_GMAIL_SYNC_ENABLED="true"
            ),
            "classifier on": lambda c: c[s]["tests"]["environment"].update(
                NEXTUP_EXTERNAL_CLASSIFIER_ENABLED="true"
            ),
            "runtime owner secret": lambda c: c[s]["api"]["secrets"].extend(
                _secrets("db_owner_password")
            ),
            "runtime migration key": lambda c: c[s]["worker"]["secrets"].extend(
                _secrets("migration_key")
            ),
            "runtime admin secret": lambda c: c[s]["scheduler"]["secrets"].extend(
                _secrets("db_admin_password")
            ),
            "frontend secret": lambda c: c[s]["frontend"].update(
                secrets=_secrets("db_app_password")
            ),
            "runtime as owner": lambda c: c[s]["api"]["environment"].update(
                NEXTUP_DB_USER="nextup_ci_owner"
            ),
            "runtime migrator role": lambda c: c[s]["worker"]["environment"].update(
                NEXTUP_DB_ROLE="migrator"
            ),
            "runtime key path": lambda c: c[s]["scheduler"]["environment"].update(
                NEXTUP_MIGRATION_KEY_FILE="/run/secrets/migration_key"
            ),
            "runtime entrypoint override": lambda c: c[s]["api"].update(entrypoint=["uvicorn"]),
            "startup waits for migrate": lambda c: c[s]["api"]["depends_on"].update(
                migrate={"condition": "service_completed_successfully"}
            ),
            "startup waits for tests": lambda c: c[s]["worker"]["depends_on"].update(tests={}),
            "migrate applies by default": lambda c: c[s]["migrate"].update(
                command=["apply", "--token", "x"]
            ),
            "migrate plan-apply by default": lambda c: c[s]["migrate"].update(
                command=["plan-apply"]
            ),
            "migrate runs alembic": lambda c: c[s]["migrate"].update(
                entrypoint=["alembic"], command=["upgrade", "head"]
            ),
            "migrate without profile": lambda c: c[s]["migrate"].pop("profiles"),
            "tests serve": lambda c: c[s]["tests"].update(
                entrypoint=["python", "-m", "app.guard", "exec", "--"]
            ),
            "tests as runtime": lambda c: c[s]["tests"]["environment"].pop("NEXTUP_DB_ROLE"),
            "postgres superuser renamed": lambda c: c[s]["postgres"]["environment"].update(
                POSTGRES_USER="nextup_ci"
            ),
            "postgres inline password": lambda c: c[s]["postgres"]["environment"].update(
                POSTGRES_PASSWORD="p" * 30
            ),
            "foreign cluster": lambda c: c[s]["postgres"].update(
                command=["postgres", "-c", "cluster_name=main"]
            ),
            "no init tmpfs": lambda c: c[s]["postgres"].update(tmpfs=["/var/lib/postgresql/data"]),
            "persistent PGDATA": lambda c: c[s]["postgres"]["environment"].update(
                PGDATA="/var/lib/postgresql/data"
            ),
            "secret from environment": lambda c: c["secrets"]["db_app_password"].update(
                environment="X"
            ),
            "secret inside repo": lambda c: c["secrets"]["db_app_password"].update(
                file=str(REPO / "secrets/db_app_password")
            ),
            "extra secret": lambda c: c["secrets"].update(other={"file": f"{SECRETS_DIR}/other"}),
            "n8n variable": lambda c: c[s]["worker"]["environment"].update(N8N_ENABLED="false"),
        }
        for label, mutation in mutations.items():
            value = copy.deepcopy(config())
            mutation(value)
            with self.subTest(label), self.assertRaises(AssertionError):
                verify_ci.validate_ci(value, SECRETS_DIR, E2E_DIR, USER)
        # Rejected even without launcher paths (layout rule, and the repository rule for a
        # run-shaped directory inside the repository).
        for source in ("/", "/srv", "/tmp/e2e", str(REPO / f"{PROJECT}-run/e2e")):
            value = copy.deepcopy(config())
            value[s]["e2e"]["volumes"][0]["source"] = source
            with self.subTest(e2e=source), self.assertRaises(AssertionError):
                verify_ci.validate_ci(value)
        for directory in ("/srv/secrets", "/tmp/secrets", "/tmp/nextup-ci-1001/other-run/secrets"):
            value = copy.deepcopy(config())
            for name in verify_ci.SECRET_NAMES:
                value["secrets"][name]["file"] = f"{directory}/{name}"
            with self.subTest(secrets=directory), self.assertRaises(AssertionError):
                verify_ci.validate_ci(value)
        for args in (
            ("/tmp/another-run/secrets", E2E_DIR, USER),  # secrets from another run
            (SECRETS_DIR, "/tmp/another-run/e2e", USER),  # e2e output of another run
            (SECRETS_DIR, E2E_DIR, "1002:1002"),  # a different user than the launcher
        ):
            with self.subTest(args=args), self.assertRaises(AssertionError):
                verify_ci.validate_ci(config(), *args)

    @unittest.skipIf(yaml is None, "PyYAML unavailable on this interpreter")
    def test_committed_ci_file_satisfies_the_contract(self):
        doc = yaml.safe_load((REPO / "compose.ci.yaml").read_text())
        self.assertNotIn("name", doc)  # the project is always chosen per run
        self.assertNotIn("volumes", doc)
        for project in (f"nextup-ci-{os.urandom(6).hex()}" for _ in range(2)):
            run_dir = f"/tmp/nextup-ci-1001/{project}-run"
            verify_ci.validate_ci(
                static_ci_render(project), f"{run_dir}/secrets", f"{run_dir}/e2e", USER
            )
        text = (REPO / "compose.ci.yaml").read_text()
        self.assertNotRegex(
            text, r"(?m)^\s+(DATABASE_URL|POSTGRES_PASSWORD|NEXTUP_ADZUNA\w*|NEXTUP_GREENHOUSE\w*):"
        )
        self.assertNotIn("synthetic-ci-only", text)
        self.assertNotIn("service_completed_successfully", text)
        self.assertNotIn("NEXTUP_CI_ARTIFACTS", text)
        for name in (
            "NEXTUP_CI_UID",
            "NEXTUP_CI_GID",
            "NEXTUP_CI_SECRETS_DIR",
            "NEXTUP_CI_E2E_DIR",
        ):
            with self.subTest(missing=name), self.assertRaises(oss_env.IsolationError):
                static_ci_render(**{name: None})


class RunnerFailureContract(unittest.TestCase):
    def test_failed_check_still_collects_and_cleans_and_returns_nonzero(self):
        stack = MagicMock(
            project=PROJECT,
            results=[],
            secrets_dir=SECRETS_DIR,
            e2e_dir=E2E_DIR,
            expected_user=USER,
        )
        stack.compose.return_value = json.dumps(config())
        stack.step.side_effect = RuntimeError("Intentional test failure")
        stack.finish.return_value = True
        with (
            patch.object(verify_ci, "Stack", return_value=stack),
            patch.object(verify_ci.os, "geteuid", return_value=1001),
        ):
            self.assertEqual(verify_ci.main({"NEXTUP_INTEGRATION_APPROVED": "1"}), 1)
        stack.finish.assert_called_once()
        stack.check.assert_not_called()
        stack.migrate.assert_not_called()

    def test_cleanup_never_requests_volume_deletion_and_removes_the_run_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            stack = object.__new__(verify_ci.Stack)
            stack.project = PROJECT
            stack.artifacts = Path(directory) / "evidence"
            (stack.artifacts / "backend").mkdir(parents=True)
            stack.run_dir = Path(directory) / "run"
            stack.secrets_dir = stack.run_dir / "secrets"
            stack.e2e_dir = stack.run_dir / "e2e"
            stack.secrets_dir.mkdir(mode=0o700, parents=True)
            stack.e2e_dir.mkdir(mode=0o700)
            stack.audit = secret_audit.SecretAudit()
            verify_ci.write_synthetic_secrets(stack.secrets_dir, stack.audit)
            stack.results = []
            stack.compose = MagicMock(return_value="")
            stack.docker_read = MagicMock(return_value=(0, b""))
            self.assertTrue(stack.finish())
            stack.compose.assert_any_call("down", "--timeout", "10")
            self.assertFalse(
                any(
                    "--volumes" in call.args or "-v" in call.args
                    for call in stack.compose.call_args_list
                )
            )
            self.assertFalse(stack.run_dir.exists())
            summary = json.loads((stack.artifacts / "summary.json").read_text())
            self.assertTrue(summary["cleanup_passed"])
            self.assertEqual(
                summary["secret_audit"], {"passed": True, "complete": True, "disclosures": 0}
            )

    def test_finish_without_an_audit_fails_closed_but_still_cleans_up(self):
        with tempfile.TemporaryDirectory() as directory:
            stack = object.__new__(verify_ci.Stack)
            stack.project = PROJECT
            stack.artifacts = Path(directory) / "evidence"
            stack.artifacts.mkdir()
            stack.run_dir = Path(directory) / "run"
            stack.e2e_dir = stack.run_dir / "e2e"
            stack.e2e_dir.mkdir(parents=True)
            stack.results = []
            stack.compose = MagicMock(return_value="")
            self.assertFalse(stack.finish())
            stack.compose.assert_any_call("down", "--timeout", "10")
            self.assertFalse(stack.run_dir.exists())
            self.assertFalse(json.loads((stack.artifacts / "summary.json").read_text())["passed"])

    def test_refuses_to_seed_over_an_existing_profile(self):
        stack = object.__new__(verify_ci.Stack)
        stack.project = PROJECT
        stack.request = MagicMock(return_value=(200, {"location": "Existing"}))
        with self.assertRaises(AssertionError):
            stack.seed()
        stack.request.assert_called_once_with("/api/profile")


@contextmanager
def redirected(environ=None):
    """The repository root and the system temp base redirected to throwaway directories and
    subprocess.run replaced by a tripwire, so that even a mutated launcher that skips a
    refusal can create nothing outside them and reach no engine.

    The real launcher runs this suite with NEXTUP_CI_SCRATCH_ROOT set to the approved scratch
    root. Unless a test supplies its own value, that variable is removed here,
    so the default layout under the redirected temp base is what gets exercised. A test that
    passes the inherited value on purpose is refused: configured-root behaviour is tested
    only against directories the test created. ``patch.dict`` restores the whole process
    environment on exit, so neither the removal nor ``environ`` leaks into other tests."""
    environ = dict(environ or {})
    inherited = os.environ.get(verify_ci.SCRATCH_VARIABLE)
    if inherited is not None and environ.get(verify_ci.SCRATCH_VARIABLE) == inherited:
        raise AssertionError("tests must not use the inherited CI scratch root")
    repo = Path(tempfile.mkdtemp(prefix="ci-repo-"))
    base = Path(os.path.realpath(tempfile.mkdtemp(prefix="ci-tmp-")))
    run = MagicMock(side_effect=AssertionError("subprocess reached"))
    try:
        with (
            patch.object(verify_ci, "ROOT", repo),
            patch.object(verify_ci.tempfile, "tempdir", str(base)),
            patch.object(verify_ci.subprocess, "run", run),
            patch.dict(os.environ, environ),
        ):
            if verify_ci.SCRATCH_VARIABLE not in environ:
                os.environ.pop(verify_ci.SCRATCH_VARIABLE, None)
            yield base, repo, run
    finally:
        for path in (repo, base):
            for root, dirs, files in os.walk(path):
                for name in dirs:
                    os.chmod(os.path.join(root, name), 0o700)
                for name in files:
                    full = os.path.join(root, name)
                    if not os.path.islink(full):
                        os.chmod(full, 0o600)
            shutil.rmtree(path, ignore_errors=True)


@contextmanager
def sandboxed_stacks(environ=None, count=1):
    """Real Stack objects inside redirected(); subprocess.run must never be reached."""
    with redirected(environ) as (base, repo, run):
        yield [verify_ci.Stack() for _ in range(count)], base, repo, run


class Hardening(unittest.TestCase):
    """Secret files, root refusal and run-directory isolation."""

    def refused(self, stack, run, fragment, secrets=()):
        with self.assertRaises(verify_ci.CIRefused) as caught:
            stack.compose("config")
        run.assert_not_called()
        self.assertIn(fragment, str(caught.exception))
        for value in secrets:
            self.assertNotIn(value, str(caught.exception))
        return caught.exception

    def values(self, stack):
        return [(stack.secrets_dir / n).read_text().strip() for n in verify_ci.SECRET_NAMES]

    def test_printed_paths_are_never_absolute(self):
        inside = verify_ci.ROOT / "test-results" / "ci" / "nextup-ci-0123456789ab"
        self.assertEqual(verify_ci.shown(inside), "test-results/ci/nextup-ci-0123456789ab")
        self.assertEqual(verify_ci.shown(Path("/home/someone/elsewhere/evidence")), "evidence")

    def test_fresh_run_layout(self):
        with sandboxed_stacks(
            {
                "COMPOSE_PROJECT_NAME": "other-stack",
                "COMPOSE_FILE": "compose.yaml",
                "UNRELATED_HOST_TOKEN": "host-value",
            },
            count=2,
        ) as (stacks, base, repo, run):
            for stack in stacks:
                self.assertNotIn("COMPOSE_FILE", stack.env)
                self.assertNotIn("COMPOSE_PROJECT_NAME", stack.env)
                # Only the allowlist, the launcher's own variables and the CI values.
                self.assertNotIn("UNRELATED_HOST_TOKEN", stack.env)
                allowed = set(verify_ci.oss_env.PASSTHROUGH_VARIABLES) | set(
                    verify_ci.LAUNCHER_VARIABLES
                )
                self.assertEqual(
                    {k for k in stack.env if k not in allowed and not k.startswith("NEXTUP_CI_")},
                    set(),
                )
                self.assertRegex(stack.project, r"^nextup-ci-[0-9a-f]{12}$")
                self.assertTrue(stack.command[-1].endswith("compose.ci.yaml"))
                self.assertEqual(stack.scratch_root, base / f"nextup-ci-{os.getuid()}")
                self.assertTrue(stack.run_dir.name.startswith(stack.project + "-"))
                for path in (stack.scratch_root, stack.run_dir, stack.secrets_dir, stack.e2e_dir):
                    self.assertEqual(stat.S_IMODE(os.lstat(path).st_mode), 0o700, path)
                self.assertEqual(stack.env["NEXTUP_CI_E2E_DIR"], str(stack.e2e_dir))
                self.assertEqual(stack.env["NEXTUP_CI_SECRETS_DIR"], str(stack.secrets_dir))
                self.assertEqual(stack.expected_user, f"{os.getuid()}:{os.getgid()}")
                values = self.values(stack)
                self.assertEqual(len(set(values)), 4)
                self.assertFalse(any(v in json.dumps(stack.env) for v in values))
                stack.preflight()
            self.assertNotEqual(stacks[0].run_dir, stacks[1].run_dir)
            run.assert_not_called()

    def test_inherited_scratch_root_is_never_used_by_default_tests(self):
        """The real launcher exports NEXTUP_CI_SCRATCH_ROOT to this suite. Tests of
        the default layout must not see it, must create nothing in it, and must leave the
        process environment exactly as they found it."""
        inherited = Path(os.path.realpath(tempfile.mkdtemp(prefix="ci-inherited-scratch-")))
        try:
            inherited.chmod(0o700)
            with patch.dict(os.environ, {verify_ci.SCRATCH_VARIABLE: str(inherited)}):
                before = dict(os.environ)
                with sandboxed_stacks(count=2) as (stacks, base, _repo, run):
                    self.assertNotIn(verify_ci.SCRATCH_VARIABLE, os.environ)
                    for stack in stacks:
                        self.assertEqual(stack.scratch_root, base / f"nextup-ci-{os.getuid()}")
                        self.assertFalse(verify_ci._inside(stack.run_dir, inherited))
                    run.assert_not_called()
                with redirected({"COMPOSE_FILE": "compose.yaml"}):
                    self.assertNotIn(verify_ci.SCRATCH_VARIABLE, os.environ)
                self.assertEqual(dict(os.environ), before)  # restored: nothing leaks between tests
            self.assertEqual(list(inherited.iterdir()), [])  # nothing created, nothing left
        finally:
            shutil.rmtree(inherited, ignore_errors=True)

    def test_configured_scratch_root_must_be_test_owned(self):
        """Configured behaviour is tested only against a directory the test created; passing
        the inherited (real) scratch root through the fixture is refused."""
        inherited = Path(os.path.realpath(tempfile.mkdtemp(prefix="ci-inherited-scratch-")))
        owned = Path(os.path.realpath(tempfile.mkdtemp(prefix="ci-owned-scratch-")))
        try:
            for path in (inherited, owned):
                path.chmod(0o700)
            with patch.dict(os.environ, {verify_ci.SCRATCH_VARIABLE: str(inherited)}):
                with sandboxed_stacks({verify_ci.SCRATCH_VARIABLE: str(owned)}) as (stacks, *_rest):
                    stack = stacks[0]
                    self.assertEqual(stack.scratch_root, owned)
                    self.assertEqual(stack.run_dir.parent, owned)
                    self.assertEqual(stat.S_IMODE(os.lstat(stack.run_dir).st_mode), 0o700)
                    stack.preflight()
                self.assertEqual(os.environ[verify_ci.SCRATCH_VARIABLE], str(inherited))
                with self.assertRaises(AssertionError) as caught:
                    with redirected({verify_ci.SCRATCH_VARIABLE: str(inherited)}):
                        pass
                self.assertIn("inherited CI scratch root", str(caught.exception))
            self.assertEqual(list(inherited.iterdir()), [])
        finally:
            for path in (inherited, owned):
                shutil.rmtree(path, ignore_errors=True)

    # ---------- secret files ----------

    def test_missing_unreadable_and_substituted_secret_files(self):
        def missing(stack):
            (stack.secrets_dir / "db_app_password").unlink()

        def unreadable(stack):
            (stack.secrets_dir / "migration_key").chmod(0)

        def loosened(stack):
            (stack.secrets_dir / "db_owner_password").chmod(0o640)

        def substituted(stack):
            # Same name, content and mode; a different file (new inode, created first).
            path = stack.secrets_dir / "db_admin_password"
            other = stack.run_dir / "substitute"
            other.write_text(path.read_text())
            other.chmod(0o600)
            os.replace(other, path)

        def symlinked(stack):
            path = stack.secrets_dir / "db_app_password"
            target = stack.run_dir / "elsewhere"
            target.write_text(path.read_text())
            target.chmod(0o600)
            path.unlink()
            path.symlink_to(target)

        def hard_linked(stack):
            os.link(stack.secrets_dir / "migration_key", stack.run_dir / "copy")

        def directory_instead(stack):
            path = stack.secrets_dir / "migration_key"
            path.unlink()
            path.mkdir(mode=0o700)

        def extra_entry(stack):
            (stack.secrets_dir / "unexpected").write_text("x")

        def bad_format(stack):
            path = stack.secrets_dir / "db_owner_password"
            path.write_text("short\n")

        def duplicate(stack):
            source = (stack.secrets_dir / "db_owner_password").read_text()
            (stack.secrets_dir / "db_app_password").write_text(source)

        def empty(stack):
            (stack.secrets_dir / "db_app_password").write_text("")

        cases = {
            "missing": (missing, "missing: db_app_password"),
            "unreadable": (unreadable, "migration_key"),
            "loosened": (loosened, "db_owner_password"),
            "substituted": (substituted, "replaced"),
            "symlinked": (symlinked, "not a regular file"),
            "hard link": (hard_linked, "hard links"),
            "directory": (directory_instead, "not a regular file"),
            "extra entry": (extra_entry, "unexpected entries: 1"),
            "bad format": (bad_format, "expected format"),
            "duplicate": (duplicate, "distinct"),
            "empty": (empty, "invalid size"),
        }
        for label, (damage, fragment) in cases.items():
            with self.subTest(label), sandboxed_stacks() as (stacks, base, repo, run):
                stack = stacks[0]
                values = self.values(stack)
                damage(stack)
                self.refused(stack, run, fragment, values)

    def test_secret_directory_loosened_or_replaced(self):
        for label in ("loosened", "replaced"):
            with self.subTest(label), sandboxed_stacks() as (stacks, base, repo, run):
                stack = stacks[0]
                if label == "loosened":
                    stack.secrets_dir.chmod(0o750)
                    self.refused(stack, run, "mode 0700")
                else:
                    moved = stack.run_dir / "old"
                    stack.secrets_dir.rename(moved)
                    shutil.copytree(moved, stack.secrets_dir)
                    stack.secrets_dir.chmod(0o700)
                    self.refused(stack, run, "replaced")

    # ---------- root refusal ----------

    def test_root_is_refused_before_any_docker_operation(self):
        with (
            redirected() as (base, repo, run),
            patch.object(verify_ci.os, "geteuid", return_value=0),
            patch.object(verify_ci, "Stack", side_effect=AssertionError("Stack built")),
            patch("sys.stderr"),
        ):
            self.assertEqual(
                verify_ci.main({"NEXTUP_INTEGRATION_APPROVED": "1"}), verify_ci.REFUSAL_EXIT
            )
            run.assert_not_called()
        with (
            redirected() as (base, repo, run),
            patch.object(verify_ci.os, "geteuid", return_value=0),
        ):
            with self.assertRaises(verify_ci.CIRefused):
                verify_ci.Stack()
            self.assertEqual(list(base.iterdir()) + list(repo.iterdir()), [])  # nothing created
            run.assert_not_called()
        with sandboxed_stacks() as (stacks, base, repo, run):
            with patch.object(verify_ci.os, "geteuid", return_value=0):
                self.refused(stacks[0], run, "effective UID 0")

    def test_launcher_root_inside_or_around_a_protected_path_is_refused(self):
        with redirected() as (base, repo, run):
            for label, protected in (
                ("root itself", str(repo)),
                ("ancestor of the root", str(repo.parent)),
                ("inside the root", str(repo / "test-results")),
            ):
                listing = base / "protected.json"
                listing.write_text(json.dumps({"paths": [protected]}))
                with (
                    self.subTest(label),
                    patch.dict(os.environ, {oss_env.PROTECTED_FILE_VARIABLE: str(listing)}),
                    self.assertRaises(verify_ci.CIRefused) as caught,
                ):
                    verify_ci.Stack()
                self.assertIn("launcher root overlaps a protected path", str(caught.exception))
                self.assertFalse((repo / "test-results").exists())  # refused before writing
            self.assertEqual([p.name for p in base.iterdir()], ["protected.json"])  # no scratch
            run.assert_not_called()
            listing.write_text(json.dumps({"paths": [str(base / "elsewhere")]}))
            with patch.dict(os.environ, {oss_env.PROTECTED_FILE_VARIABLE: str(listing)}):
                stack = verify_ci.Stack()  # an unrelated protected path does not block the run
                with patch.object(verify_ci, "ROOT", base / "elsewhere"):
                    self.assertRaises(verify_ci.CIRefused, stack.preflight)  # checked every time

    def test_postgres_bootstrap_root_phase_is_unchanged(self):
        text = (REPO / "compose.ci.yaml").read_text()
        self.assertIn("install -d -m 0700 -o postgres -g postgres /run/nextup-initdb", text)
        self.assertIn("exec docker-entrypoint.sh", text)

    # ---------- run-directory isolation ----------

    def test_scratch_root_boundaries(self):
        def protected_list(base, paths):
            path = base / "protected.json"
            path.write_text(json.dumps({"paths": [str(p) for p in paths]}))
            return str(path)

        # Refused before anything is created: the traversal target must not appear.
        probe = Path(os.path.realpath(tempfile.mkdtemp(prefix="ci-scratch-probe-")))
        try:
            (probe / "a").mkdir()
            for label, environ, fragment in (
                ("relative", {verify_ci.SCRATCH_VARIABLE: "relative/dir"}, "absolute"),
                ("traversal", {verify_ci.SCRATCH_VARIABLE: f"{probe}/a/../x"}, "traversal"),
            ):
                with self.subTest(label), self.assertRaises(verify_ci.CIRefused) as caught:
                    with sandboxed_stacks(environ):
                        pass
                self.assertIn(fragment, str(caught.exception))
            self.assertFalse((probe / "x").exists())
            self.assertFalse(Path("relative").exists())
        finally:
            shutil.rmtree(probe, ignore_errors=True)

        # inside the repository, a symlinked root, a git tree, a protected path, a loose mode
        with tempfile.TemporaryDirectory() as outer:
            outer = Path(os.path.realpath(outer))
            real = outer / "real"
            real.mkdir(mode=0o700)
            link = outer / "link"
            link.symlink_to(real)
            git_tree = outer / "tree"
            (git_tree / ".git").mkdir(parents=True)
            (git_tree / "scratch").mkdir(mode=0o700)
            loose = outer / "loose"
            loose.mkdir(mode=0o755)
            loose.chmod(0o755)
            guarded = outer / "guarded"
            guarded.mkdir(mode=0o700)
            cases = {
                "symlinked root": ({verify_ci.SCRATCH_VARIABLE: str(link)}, "symlinks"),
                "git working tree": (
                    {verify_ci.SCRATCH_VARIABLE: str(git_tree / "scratch")},
                    "git working tree",
                ),
                "loose mode": ({verify_ci.SCRATCH_VARIABLE: str(loose)}, "mode 0700"),
                "protected path": (
                    {
                        verify_ci.SCRATCH_VARIABLE: str(guarded),
                        oss_env.PROTECTED_FILE_VARIABLE: protected_list(outer, [outer]),
                    },
                    "protected path",
                ),
            }
            for label, (environ, fragment) in cases.items():
                with self.subTest(label), self.assertRaises(verify_ci.CIRefused) as caught:
                    with sandboxed_stacks(environ):
                        pass
                self.assertIn(fragment, str(caught.exception))
        # inside the (sandboxed) repository itself
        with self.assertRaises(verify_ci.CIRefused) as caught:
            repo = Path(tempfile.mkdtemp(prefix="ci-repo-"))
            try:
                inside = repo / "scratch"
                inside.mkdir(mode=0o700)
                with (
                    patch.object(verify_ci, "ROOT", repo),
                    patch.dict(os.environ, {verify_ci.SCRATCH_VARIABLE: str(inside)}),
                ):
                    verify_ci.Stack()
            finally:
                shutil.rmtree(repo, ignore_errors=True)
        self.assertIn("repository", str(caught.exception))

    def test_e2e_directory_substitution_and_tampering(self):
        def replaced(stack):
            stack.e2e_dir.rename(stack.run_dir / "e2e-old")  # keeps the old inode in use
            stack.e2e_dir.mkdir(mode=0o700)

        def symlinked(stack):
            other = stack.run_dir / "other"
            other.mkdir(mode=0o700)
            stack.e2e_dir.rmdir()
            stack.e2e_dir.symlink_to(other)

        def loosened(stack):
            stack.e2e_dir.chmod(0o777)

        def variable(stack):
            stack.env["NEXTUP_CI_E2E_DIR"] = "/"

        def run_replaced(stack):
            moved = stack.run_dir.parent / (stack.run_dir.name + "-moved")
            stack.run_dir.rename(moved)
            shutil.copytree(moved, stack.run_dir, symlinks=True)
            stack.run_dir.chmod(0o700)

        cases = {
            "replaced": (replaced, "replaced"),
            "symlinked": (symlinked, "symlinks"),
            "loosened": (loosened, "mode 0700"),
            "variable": (variable, "do not match"),
            "run directory replaced": (run_replaced, "replaced"),
        }
        for label, (damage, fragment) in cases.items():
            with self.subTest(label), sandboxed_stacks() as (stacks, base, repo, run):
                damage(stacks[0])
                self.refused(stacks[0], run, fragment)

    def test_finish_copies_only_a_regular_e2e_result(self):
        for label in ("regular", "symlink"):
            with self.subTest(label), sandboxed_stacks() as (stacks, base, repo, run):
                stack = stacks[0]
                stack.results = [{"check": "browser-tests", "exit_code": 0}]
                stack.compose = MagicMock(return_value="")
                stack.docker_read = MagicMock(return_value=(0, b""))
                outside = base / "outside.xml"
                outside.write_text("<outside/>")
                if label == "regular":
                    (stack.e2e_dir / "browser.xml").write_text("<testsuite/>")
                else:
                    (stack.e2e_dir / "browser.xml").symlink_to(outside)
                cleaned = stack.finish()
                copied = stack.artifacts / "browser/browser.xml"
                if label == "regular":
                    self.assertTrue(cleaned and copied.read_text() == "<testsuite/>")
                else:
                    self.assertFalse(cleaned or copied.exists())
                self.assertFalse(stack.run_dir.exists())


INIT_PLAN = [
    "nextup-guard: PLAN mode=INIT env=ci database=nextup_ci from=empty to=0029 steps=29",
    "nextup-guard: steps: 0001, ..., 0029",
    "nextup-guard: confirmation=0123456789ab expires_in=600s single-use",
    "nextup-guard: awaiting confirmation",
]


class GuardedMigrationFlow(unittest.TestCase):
    """`guard plan-apply` keeps the token in the guard process; the launcher
    only confirms an INIT plan with the one-time code shown."""

    def setUp(self):
        self._dirs = []

    def tearDown(self):
        for path in self._dirs:
            shutil.rmtree(path, ignore_errors=True)

    def stack(self):
        stack = object.__new__(verify_ci.Stack)
        stack.results = []
        stack.artifacts = Path(tempfile.mkdtemp())
        self._dirs.append(stack.artifacts)
        stack.project = PROJECT
        stack.command = ["docker", "compose", "--project-name", PROJECT]
        stack.env = {"PATH": "/usr/bin", "NEXTUP_CI_UID": "1001"}
        stack.preflight = MagicMock()
        stack.audit = secret_audit.SecretAudit()
        return stack

    def fake(self, plan, after, returncode=0, awaited=True):
        calls = {}

        def plan_apply(command, *, decide, cwd, env, timeout):
            calls.update(command=command, env=env, timeout=timeout)
            session = guard_session.Session(lines=list(plan), awaited=awaited)
            session.code = "0123456789ab" if awaited else None
            if awaited:
                calls["answer"] = decide(list(plan), session.code)
                session.confirmed = calls["answer"] is not None
                session.lines += after if session.confirmed else ["nextup-guard: REFUSE NXG-A11"]
                session.returncode = returncode if session.confirmed else 3
            else:
                session.returncode = returncode
            return session

        return calls, plan_apply

    def test_init_is_confirmed_and_no_token_ever_reaches_the_launcher(self):
        stack = self.stack()
        calls, fake = self.fake(INIT_PLAN, ["nextup-guard: APPLIED mode=INIT to=0029 env=ci"])
        with patch.object(verify_ci.guard_session, "plan_apply", fake), patch("builtins.print"):
            stack.migrate()
        self.assertEqual(
            calls["command"],
            [
                *stack.command,
                "--profile",
                "migrate",
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "migrate",
                "plan-apply",
            ],
        )
        self.assertEqual(calls["answer"], "0123456789ab")
        self.assertFalse(any("token" in part or "nxa1." in part for part in calls["command"]))
        self.assertNotIn("nxa1.", json.dumps(calls["env"]))
        self.assertEqual(stack.results, [{"check": "migration", "exit_code": 0}])
        self.assertIn("APPLIED mode=INIT", (stack.artifacts / "migration.log").read_text())
        self.assertEqual(stack.audit.report()["secrets_registered"], {})  # no token to register
        stack.preflight.assert_called_once()

    def test_only_an_init_plan_is_ever_confirmed(self):
        for plan, after, returncode, awaited in (
            (["nextup-guard: PLAN mode=UPGRADE env=ci", *INIT_PLAN[2:]], [], 0, True),
            (
                ["nextup-guard: PLAN mode=NOOP env=ci", "nextup-guard: nothing to apply"],
                [],
                0,
                False,
            ),
            (["nextup-guard: REFUSE NXG-I04 wrong role"], [], 3, False),
            (INIT_PLAN, ["nextup-guard: REFUSE NXG-A04 expired"], 3, True),
        ):
            stack = self.stack()
            calls, fake = self.fake(plan, after, returncode, awaited)
            with (
                self.subTest(plan=plan[0], after=after),
                patch.object(verify_ci.guard_session, "plan_apply", fake),
                patch("builtins.print"),
                self.assertRaises(RuntimeError),
            ):
                stack.migrate()
            if plan[0].startswith("nextup-guard: PLAN mode=UPGRADE"):
                self.assertIsNone(calls["answer"])  # declined: stdin closed, nothing applied
            self.assertEqual(stack.results, [{"check": "migration", "exit_code": 1}])

    def test_a_leaked_token_line_would_still_be_masked_in_the_log(self):
        stack = self.stack()
        leaky = [*INIT_PLAN[:-1], f"nextup-guard: token={TOKEN}", INIT_PLAN[-1]]
        _, fake = self.fake(leaky, ["nextup-guard: APPLIED mode=INIT to=0029 env=ci"])
        with patch.object(verify_ci.guard_session, "plan_apply", fake), patch("builtins.print"):
            stack.migrate()
        self.assertNotIn(TOKEN, (stack.artifacts / "migration.log").read_text())

    def test_step_pipes_the_token_to_the_subprocess_stdin_only(self):
        stack = object.__new__(verify_ci.Stack)
        stack.artifacts = Path(tempfile.mkdtemp())
        self._dirs.append(stack.artifacts)
        stack.results, stack.env = [], {"PATH": "/usr/bin"}
        stack.preflight = MagicMock()
        with patch.object(verify_ci.subprocess, "run") as run, patch("builtins.print"):
            run.return_value = MagicMock(returncode=0)
            stack.step(
                "migration-apply",
                ["docker", "compose", "run", "-T", "migrate", "apply"],
                input_text=TOKEN + "\n",
            )
        command, kwargs = run.call_args.args[0], run.call_args.kwargs
        self.assertFalse(any(TOKEN in part for part in command))
        self.assertEqual(kwargs["input"], (TOKEN + "\n").encode())
        self.assertNotIn(TOKEN, json.dumps(kwargs["env"]))
        stack.preflight.assert_called_once()

    def test_runtime_services_start_only_after_the_guarded_migration(self):
        source = (REPO / "scripts/verify_ci.py").read_text()
        main = source[source.index("def main(") :]
        order = [
            main.index(marker) for marker in ('"data-services"', "stack.migrate()", '"startup"')
        ]
        self.assertEqual(order, sorted(order))
        self.assertNotIn('"alembic", "upgrade"', source)
        self.assertNotIn('exec", "-T", "api", "alembic"', source)
        for privileged in (
            "backend-lint",
            "backend-format",
            "python-dependencies",
            "migration-roundtrips",
            "backend-tests",
        ):
            self.assertRegex(main, rf'stack\.tests\(\s*"{privileged}"')
        self.assertIsNone(re.search(r"DATABASE_URL\s*=", source))


CONTAINER = "c" * 64


class SecretAuditIntegration(unittest.TestCase):
    """Exact-value audit inside finish(), before any secret is removed."""

    def values(self, stack):
        return [(stack.secrets_dir / n).read_text().strip() for n in verify_ci.SECRET_NAMES]

    def engine(self, stack, logs="", inspect=None, environ=b""):
        stack.compose = MagicMock(
            side_effect=lambda *a: logs if a == ("logs", "--no-color") else ""
        )
        items = inspect or []

        def docker(args):
            self.assertTrue(secret_audit.allowed_engine_command(stack.project, args), args)
            if args[0] == "ps":
                return 0, "\n".join(i["Id"] for i in items).encode()
            if args[0] == "inspect":
                return 0, json.dumps(items).encode()
            return 0, environ

        stack.docker_read = MagicMock(side_effect=docker)

    def item(self, stack, running=False, project=None, **config):
        return {
            "Id": CONTAINER,
            "Name": f"/{stack.project}-api-1",
            "Config": {
                "Labels": {"com.docker.compose.project": project or stack.project},
                **config,
            },
            "State": {"Running": running},
        }

    def assert_no_plaintext(self, stack, values, files=("secret_audit.json", "summary.json")):
        for name in files:
            text = (stack.artifacts / name).read_bytes()
            for value in values:
                for needle in secret_audit.variants(value).values():
                    self.assertNotIn(needle, text, name)

    def finish(self, stack):
        with patch("builtins.print"):
            return stack.finish()

    def test_clean_run_passes_and_retains_counts_only(self):
        with sandboxed_stacks() as (stacks, base, repo, run):
            stack = stacks[0]
            values = self.values(stack)
            self.engine(
                stack,
                logs="api-1 | started",
                inspect=[
                    self.item(stack, Env=["NEXTUP_DB_PASSWORD_FILE=/run/secrets/db_app_password"])
                ],
            )
            self.assertTrue(self.finish(stack))
            report = json.loads((stack.artifacts / "secret_audit.json").read_text())
            self.assertTrue(report["passed"] and report["complete"])
            self.assertEqual(report["disclosures"], 0)
            self.assertEqual(sorted(report["secrets_registered"]), sorted(verify_ci.SECRET_NAMES))
            for path in stack.artifacts.rglob("*"):
                if path.is_file():
                    data = path.read_bytes()
                    for value in values:
                        for needle in secret_audit.variants(value).values():
                            self.assertNotIn(needle, data, path.name)
            stack.compose.assert_any_call("down", "--timeout", "10")
            self.assertFalse(stack.run_dir.exists())

    def test_leak_in_evidence_fails_the_run_without_echoing_the_value(self):
        import base64

        with sandboxed_stacks() as (stacks, base, repo, run):
            stack = stacks[0]
            values = self.values(stack)
            leak = base64.b64encode(("user:" + values[2]).encode()).decode()
            (stack.artifacts / "backend" / "leak.log").write_text(f"Authorization: Basic {leak}\n")
            self.engine(stack)
            self.assertFalse(self.finish(stack))
            report = json.loads((stack.artifacts / "secret_audit.json").read_text())
            self.assertFalse(report["passed"])
            sources = {(f["secret"], f["source"]) for f in report["findings"]}
            self.assertIn(("db_app_password", "evidence:backend/leak.log"), sources)
            self.assertTrue(any(f["variant"].startswith("base64@") for f in report["findings"]))
            self.assert_no_plaintext(stack, values)
            summary = json.loads((stack.artifacts / "summary.json").read_text())
            self.assertIn("secret-audit", summary["collection_errors"])
            stack.compose.assert_any_call("down", "--timeout", "10")
            self.assertFalse(stack.run_dir.exists())

    def test_leak_in_full_compose_logs(self):
        with sandboxed_stacks() as (stacks, base, repo, run):
            stack = stacks[0]
            values = self.values(stack)
            self.engine(stack, logs=f"worker-1 | password={values[1]}")
            self.assertFalse(self.finish(stack))
            report = json.loads((stack.artifacts / "secret_audit.json").read_text())
            self.assertIn(
                ("db_owner_password", "engine:compose-logs"),
                {(f["secret"], f["source"]) for f in report["findings"]},
            )
            self.assert_no_plaintext(stack, values)

    def test_token_in_container_metadata_is_detected(self):
        with sandboxed_stacks() as (stacks, base, repo, run):
            stack = stacks[0]
            stack.audit.add("migration_token", TOKEN)
            self.engine(stack, inspect=[self.item(stack, Cmd=["apply", "--token", TOKEN])])
            self.assertFalse(self.finish(stack))
            report = json.loads((stack.artifacts / "secret_audit.json").read_text())
            self.assertIn(
                ("migration_token", "raw", f"engine:inspect:{stack.project}-api-1"),
                {(f["secret"], f["variant"], f["source"]) for f in report["findings"]},
            )
            self.assert_no_plaintext(stack, [TOKEN])

    def test_an_unregistered_token_is_caught_by_its_format(self):
        with sandboxed_stacks() as (stacks, base, repo, run):
            stack = stacks[0]  # the launcher never holds the token: nothing is registered
            self.engine(stack, logs=f"migrate-1 | nextup-guard: token={TOKEN}")
            (stack.artifacts / "migration.log").write_text("nextup-guard: token=<masked>\n")
            self.assertFalse(self.finish(stack))
            report = json.loads((stack.artifacts / "secret_audit.json").read_text())
            self.assertEqual(
                {(f["secret"], f["variant"], f["source"]) for f in report["findings"]},
                {("migration_token", "token-format", "engine:compose-logs")},
            )
            self.assertNotIn(TOKEN, (stack.artifacts / "secret_audit.json").read_text())

    def test_running_container_process_environment_is_scanned(self):
        with sandboxed_stacks() as (stacks, base, repo, run):
            stack = stacks[0]
            values = self.values(stack)
            self.engine(
                stack,
                inspect=[self.item(stack, running=True)],
                environ=f"PATH=/usr/bin\0NEXTUP_DB_PASSWORD={values[2]}\0".encode(),
            )
            self.assertFalse(self.finish(stack))
            report = json.loads((stack.artifacts / "secret_audit.json").read_text())
            self.assertIn(
                f"engine:environ:{stack.project}-api-1", {f["source"] for f in report["findings"]}
            )
            calls = [c.args[0] for c in stack.docker_read.call_args_list]
            self.assertIn(["exec", CONTAINER, "cat", "/proc/1/environ"], calls)

    def test_a_foreign_container_is_never_scanned(self):
        with sandboxed_stacks() as (stacks, base, repo, run):
            stack = stacks[0]
            values = self.values(stack)
            foreign = self.item(
                stack, running=True, project="private-stack", Env=[f"X={values[0]}"]
            )
            foreign["Name"] = "/private-stack-db-1"
            self.engine(stack, inspect=[foreign], environ=values[0].encode())
            self.assertFalse(self.finish(stack))
            report = json.loads((stack.artifacts / "secret_audit.json").read_text())
            self.assertEqual(report["findings"], [])
            self.assertEqual(
                report["anomalies"],
                [{"source": "engine:inspect:container-0", "kind": "foreign project excluded"}],
            )
            self.assertNotIn("private-stack", (stack.artifacts / "secret_audit.json").read_text())
            self.assertFalse(any(c.args[0][0] == "exec" for c in stack.docker_read.call_args_list))

    def test_engine_failure_or_interruption_still_cleans_up(self):
        for error in (RuntimeError("engine gone"), KeyboardInterrupt()):
            with (
                self.subTest(error=type(error).__name__),
                sandboxed_stacks() as (stacks, base, repo, run),
            ):
                stack = stacks[0]
                self.engine(stack)
                stack.docker_read = MagicMock(side_effect=error)
                self.assertFalse(self.finish(stack))
                report = json.loads((stack.artifacts / "secret_audit.json").read_text())
                self.assertFalse(report["complete"] or report["passed"])
                self.assertIn("engine", report["failed_sources"])
                stack.compose.assert_any_call("down", "--timeout", "10")
                self.assertFalse(stack.run_dir.exists())

    def test_tampered_run_still_audits_with_the_values_captured_at_creation(self):
        with sandboxed_stacks() as (stacks, base, repo, run):
            stack = stacks[0]
            values = self.values(stack)
            for name in verify_ci.SECRET_NAMES:
                (stack.secrets_dir / name).unlink()
            (stack.artifacts / "late.log").write_text(values[3])
            self.engine(stack)
            stack.compose = MagicMock(side_effect=verify_ci.CIRefused("Refused: tampered"))
            self.assertFalse(self.finish(stack))
            report = json.loads((stack.artifacts / "secret_audit.json").read_text())
            self.assertIn(
                ("migration_key", "evidence:late.log"),
                {(f["secret"], f["source"]) for f in report["findings"]},
            )
            self.assertFalse(report["complete"])
            self.assertFalse(stack.run_dir.exists())

    def test_console_output_is_teed_into_the_evidence_and_scanned(self):
        import io

        with sandboxed_stacks() as (stacks, base, repo, run):
            stack = stacks[0]
            values = self.values(stack)
            self.engine(stack)
            with patch.object(sys, "stdout", io.StringIO()):
                with stack.console():
                    print("diagnostic", values[0])
                    cleaned = stack.finish()
            self.assertFalse(cleaned)
            report = json.loads((stack.artifacts / "secret_audit.json").read_text())
            self.assertIn(
                ("db_admin_password", "evidence:console.log"),
                {(f["secret"], f["source"]) for f in report["findings"]},
            )

    def test_engine_reads_are_scoped_to_the_run_and_preflighted(self):
        with sandboxed_stacks() as (stacks, base, repo, run):
            stack = stacks[0]
            for args in (
                ["rm", "-f", CONTAINER],
                ["ps", "-aq"],
                ["inspect", "private-db"],
                ["ps", "-aq", "--no-trunc", "--filter", "label=com.docker.compose.project=other"],
                ["exec", CONTAINER, "sh", "-c", "env"],
            ):
                with self.subTest(args=args), self.assertRaises(PermissionError):
                    stack.docker_read(args)
            run.assert_not_called()
            run.side_effect = None
            run.return_value = MagicMock(returncode=0, stdout=b"")
            args = [
                "ps",
                "-aq",
                "--no-trunc",
                "--filter",
                f"label=com.docker.compose.project={stack.project}",
            ]
            self.assertEqual(stack.docker_read(args), (0, b""))
            self.assertEqual(run.call_args.args[0], ["docker", *args])
            (stack.secrets_dir / "migration_key").unlink()
            with self.assertRaises(verify_ci.CIRefused):
                stack.docker_read(args)
            self.assertEqual(run.call_count, 1)


class DependencyReview(unittest.TestCase):
    def test_current_lockfiles_have_reviewable_origins_and_hashes(self):
        result = inventory()
        self.assertGreater(len(result["python"]), 0)
        self.assertGreater(len(result["node"]), 0)
        self.assertIn("CVE status not checked", result["scope"])


class LibpqVariables(unittest.TestCase):
    """No PostgreSQL client variable in the launcher's shell or in a CI service."""

    def test_shell_variables_are_refused_before_anything_is_created(self):
        approved = {"NEXTUP_INTEGRATION_APPROVED": "1", "PATH": "/usr/bin:/bin"}
        verify_ci.refuse_client_variables({**approved, "PGDATA": "/x", "PG_MAJOR": "17"})
        for name in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS", "PGPORT", "PGNEW"):
            with self.subTest(name=name):
                with self.assertRaises(verify_ci.CIRefused) as caught:
                    verify_ci.refuse_client_variables({**approved, name: "SENTINEL-value"})
                self.assertIn(name, str(caught.exception))
                self.assertNotIn("SENTINEL-value", str(caught.exception))
                with (
                    patch.object(verify_ci, "Stack") as stack,
                    patch.object(verify_ci, "refuse_root"),
                    patch("sys.stderr"),
                ):
                    code = verify_ci.main({**approved, name: "SENTINEL-value"})
                self.assertEqual(code, verify_ci.REFUSAL_EXIT)
                stack.assert_not_called()

    @unittest.skipIf(yaml is None, "PyYAML unavailable on this interpreter")
    def test_every_service_is_checked_and_only_postgres_keeps_its_data_directory(self):
        project = "nextup-ci-0123456789ab"
        run_dir = f"/tmp/nextup-ci-1001/{project}-run"
        config = static_ci_render(project)
        verify_ci.validate_ci(config, f"{run_dir}/secrets", f"{run_dir}/e2e", USER)
        self.assertIn("PGDATA", config["services"]["postgres"]["environment"])
        for service in sorted(config["services"]):
            for name in ("PGHOSTADDR", "PGSERVICE", "PGDATA"):
                if service == "postgres" and name == "PGDATA":
                    continue
                damaged = copy.deepcopy(config)
                damaged["services"][service].setdefault("environment", {})[name] = "x"
                with self.subTest(service=service, name=name), self.assertRaises(AssertionError):
                    verify_ci.validate_ci(damaged, f"{run_dir}/secrets", f"{run_dir}/e2e", USER)


if __name__ == "__main__":
    unittest.main()
