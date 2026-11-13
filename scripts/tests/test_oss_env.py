"""Static isolation checks of the committed Compose, env and editor files. No Docker.

YAML parsing needs PyYAML; those tests skip (with a reason) where it is unavailable.
Set NEXTUP_PROTECTED_RESOURCES_FILE to a private denylist (outside the repository) to
also check every rendered identifier against known protected resources.
"""

import copy
import json
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import oss_env

try:
    import yaml
except ImportError:  # pragma: no cover - depends on the host interpreter
    yaml = None

REPO = Path(__file__).resolve().parents[2]
DEV, STG = oss_env.ENVIRONMENTS["dev"], oss_env.ENVIRONMENTS["staging"]
needs_yaml = unittest.skipIf(yaml is None, "PyYAML unavailable on this interpreter")


INSTANCE = "3f1c9a52-6a2e-4b7d-9c1e-2d4f6a8b0c1e"
SENTINEL = "SENTINEL_secret_value_never_rendered_91"


def variables(env, **extra):
    """Non-secret identity values only: the env files carry no password, token or key."""
    values = {f"{env.prefix}INSTANCE_ID": INSTANCE}
    if env.name == "dev":
        values.update({f"{env.prefix}LOCAL_UID": "1000", f"{env.prefix}LOCAL_GID": "1000"})
    else:
        values.update(
            {
                f"{env.prefix}SECRETS_DIR": "/srv/nextup-oss-stg/secrets",
                f"{env.prefix}SECRETS_GID": "1500",
            }
        )
    values.update(extra)
    return values


def protected():
    return oss_env.load_protected(os.environ.get(oss_env.PROTECTED_FILE_VARIABLE))


def raw(name):
    return yaml.safe_load((REPO / name).read_text())


@needs_yaml
class RenderedEnvironments(unittest.TestCase):
    def test_dev_staging_and_debug_pass_isolation(self):
        for env, extra in ((DEV, ()), (DEV, ("compose.debug.yaml",)), (STG, ())):
            with self.subTest(env=env.name, extra=extra):
                config = oss_env.static_config(env, variables(env), extra=extra)
                oss_env.validate_config(config, env, protected())

    def test_identity_values_are_required(self):
        required = {
            DEV: ("INSTANCE_ID", "LOCAL_UID", "LOCAL_GID"),
            STG: ("INSTANCE_ID", "SECRETS_DIR", "SECRETS_GID"),
        }
        for env, keys in required.items():
            for key in keys:
                for value in (None, ""):
                    with self.subTest(env=env.name, key=key, value=value):
                        values = variables(env)
                        if value is None:
                            values.pop(env.prefix + key)
                        else:
                            values[env.prefix + key] = value
                        with self.assertRaisesRegex(oss_env.IsolationError, env.prefix + key):
                            oss_env.static_config(env, values)

    def test_environment_variables_cannot_change_identity(self):
        hostile = {
            "COMPOSE_PROJECT_NAME": "other-stack",
            "POSTGRES_DB": "other_db",
            "POSTGRES_USER": "other_user",
            "DATABASE_URL": "postgresql+psycopg://x:y@elsewhere/other_db",
            "NEXTUP_DEV_POSTGRES_DB": "other_db",
            "NEXTUP_STG_POSTGRES_DB": "other_db",
            "NEXTUP_DEV_DB_NAME": "other_db",
            "NEXTUP_DB_USER": "other_user",
            "NEXTUP_DB_PASSWORD": "inline",
            "GMAIL_REFRESH_TOKEN": "token",
            "NEXTUP_STG_LIVE_JOB_FETCH_ENABLED": "true",
            "NEXTUP_DEV_LIVE_JOB_FETCH_ENABLED": "true",
        }
        for env in (DEV, STG):
            with self.subTest(env=env.name):
                config = oss_env.static_config(env, variables(env, **hostile))
                oss_env.validate_config(config, env, protected())
                self.assertEqual(config["name"], env.project)
                self.assertEqual(
                    {v["name"] for v in config["volumes"].values()},
                    {
                        f"{env.project}_{k}"
                        for k in ("postgres-data", "redis-data", "scheduler-data")
                    },
                )

    def test_identity_fields_are_literals_in_every_overlay(self):
        for env in (DEV, STG):
            doc = raw(env.overlay)
            self.assertEqual(doc["name"], env.project)
            for volume in doc["volumes"].values():
                self.assertNotIn("$", volume["name"])
            for name, service in doc["services"].items():
                self.assertNotIn("$", str(service.get("image", "")), name)
                for port in service.get("ports", []):
                    self.assertTrue(port.startswith("127.0.0.1:"), (name, port))
            pg = doc["services"]["postgres"]
            self.assertEqual(
                (pg["environment"]["POSTGRES_DB"], pg["environment"]["POSTGRES_USER"]),
                ("postgres", env.role("admin")),
            )
            self.assertEqual(pg["command"], ["postgres", "-c", f"cluster_name={env.project}"])
            for name in ("api", "worker", "scheduler", "migrate"):
                values = oss_env.static_config(env, variables(env))["services"][name]["environment"]
                for key in ("NEXTUP_ENV", "NEXTUP_DB_NAME", "NEXTUP_DB_USER", "NEXTUP_DB_HOST"):
                    self.assertIn(key, values, name)
            self.assertNotIn(
                "${",
                json.dumps(
                    {
                        k: v
                        for k, v in doc["services"]["migrate"]["environment"].items()
                        if k not in ("NEXTUP_INSTANCE_ID",)
                        and not k.endswith(("_SECONDS", "_DAYS", "_ENABLED", "_SIZE"))
                    }
                ),
            )

    def test_every_overlay_variable_is_in_the_env_allowlist(self):
        # `$${VAR}` is a container-runtime reference, not Compose interpolation.
        interpolated = re.compile(r"(?<!\$)\$\{([A-Z0-9_]+)")
        for env in (DEV, STG):
            used = set(interpolated.findall((REPO / env.overlay).read_text()))
            self.assertTrue(used <= set(env.allowed_keys), sorted(used - set(env.allowed_keys)))
        base = (REPO / "compose.base.yaml").read_text()
        self.assertEqual(set(interpolated.findall(base)), set())

    def test_base_file_carries_no_identity_ports_or_credentials(self):
        doc = raw("compose.base.yaml")
        self.assertNotIn("name", doc)
        for name, service in doc["services"].items():
            self.assertNotIn("ports", service, name)
            if service.get("build"):
                self.assertNotIn("image", service, name)
        self.assertTrue(all(not v for v in doc["volumes"].values()))
        with self.assertRaises(oss_env.IsolationError):
            oss_env.validate_config(raw("compose.base.yaml"), DEV)

    def test_raw_compose_in_this_directory_fails(self):
        doc = raw("compose.yaml")
        self.assertEqual(doc["services"], {})
        with self.assertRaisesRegex(oss_env.IsolationError, "NEXTUP_RAW_COMPOSE_IS_DISABLED"):
            oss_env.interpolate(doc, {})

    def test_migrations_go_through_the_guard_and_are_never_awaited(self):
        """Acceptance 8: no startup path runs migrations."""
        for env in (DEV, STG):
            services = oss_env.static_config(env, variables(env))["services"]
            self.assertEqual(services["migrate"]["profiles"], ["migrate"])
            self.assertEqual(services["migrate"]["entrypoint"], ["python", "-m", "app.guard"])
            self.assertEqual(services["migrate"]["command"], ["plan"])  # read-only default
            self.assertEqual(services["migrate"]["restart"], "no")
            for name, service in services.items():
                self.assertNotIn("migrate", service.get("depends_on", {}), name)
                self.assertNotIn("alembic", json.dumps(service.get("command", [])), name)
                if name in ("api", "worker", "scheduler"):
                    self.assertNotIn("entrypoint", service, name)  # keeps the image's guard exec

    def test_runtime_services_never_receive_privileged_credentials(self):
        """Acceptance 3: secret scoping per service and environment keys."""
        for env in (DEV, STG):
            services = oss_env.static_config(env, variables(env))["services"]
            for name in ("api", "worker", "scheduler"):
                service = services[name]
                # Only the api also receives the local-session setup code.
                expected = (
                    ["db_app_password", "setup_code"] if name == "api" else ["db_app_password"]
                )
                self.assertEqual(service["secrets"], expected, name)
                self.assertEqual(
                    service["environment"].get("NEXTUP_SETUP_CODE_FILE"),
                    "/run/secrets/setup_code" if name == "api" else None,
                    name,
                )
                self.assertEqual(service["environment"]["NEXTUP_DB_USER"], env.role("app"))
                for key in service["environment"]:
                    self.assertFalse(key.startswith(("NEXTUP_MIGRATION", "POSTGRES_")), (name, key))
                    self.assertNotEqual(key, "NEXTUP_DB_ROLE", name)
            self.assertEqual(
                sorted(services["migrate"]["secrets"]), ["db_owner_password", "migration_key"]
            )
            self.assertEqual(
                sorted(services["postgres"]["secrets"]),
                ["db_admin_password", "db_app_password", "db_owner_password"],
            )
            for name in ("redis", "frontend") + (("e2e",) if env is DEV else ()):
                self.assertNotIn("secrets", services[name], name)

    def test_rendered_configuration_never_contains_secret_values(self):
        """Static approximation of the render."""
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (
                "compose.base.yaml",
                "compose.dev.yaml",
                "compose.staging.yaml",
                "compose.debug.yaml",
            ):
                shutil.copy(REPO / name, root / name)
            secrets = root / ".secrets/dev"
            secrets.mkdir(parents=True)
            for index, name in enumerate(oss_env.SECRET_NAMES):
                (secrets / name).write_text(f"{SENTINEL}{index}\n")
            for env, extra in ((DEV, ()), (DEV, ("compose.debug.yaml",)), (STG, ())):
                values = variables(env)
                if env is STG:
                    values[f"{env.prefix}SECRETS_DIR"] = str(secrets)
                rendered = json.dumps(oss_env.static_config(env, values, root=root, extra=extra))
                self.assertNotIn(SENTINEL, rendered)
                for service in oss_env.static_config(env, values, root=root, extra=extra)[
                    "services"
                ].values():
                    for key in service.get("environment") or {}:
                        self.assertFalse(
                            key.endswith(oss_env.SECRET_SUFFIXES) and not key.endswith("_FILE"), key
                        )

    def test_integrations_are_disabled_and_have_no_credentials(self):
        for env in (DEV, STG):
            services = oss_env.static_config(env, variables(env))["services"]
            for name in ("api", "worker", "scheduler", "migrate"):
                values = services[name]["environment"]
                for flag in oss_env.INTEGRATION_FLAGS:
                    self.assertEqual(values[flag], "false", (env.name, name, flag))
                for key in values:
                    self.assertNotRegex(
                        key, r"GOOGLE|GMAIL_REFRESH|ADZUNA|GREENHOUSE|N8N", (name, key)
                    )

    def test_first_boot_script_is_mounted_read_only_into_postgres_only(self):
        for env in (DEV, STG):
            services = oss_env.static_config(env, variables(env))["services"]
            self.assertIn(
                "./backend/docker/initdb:/docker-entrypoint-initdb.d:ro",
                services["postgres"]["volumes"],
            )
            for name, service in services.items():
                if name != "postgres":
                    self.assertNotIn("initdb", json.dumps(service.get("volumes", [])), name)

    def test_ci_stack_is_disposable_and_guarded(self):
        # Full CI contract: scripts/tests/test_ci.py (validate_ci on a static render).
        doc = raw("compose.ci.yaml")
        self.assertNotIn("name", doc)
        self.assertNotIn("volumes", doc)
        services = doc["services"]
        self.assertEqual(services["migrate"]["entrypoint"], ["python", "-m", "app.guard"])
        self.assertEqual(services["migrate"]["command"], ["plan"])
        for name, service in services.items():
            self.assertNotIn("migrate", service.get("depends_on", {}) or {}, name)

    def test_no_compose_file_reaches_outside_the_stack(self):
        for name in (
            "compose.base.yaml",
            "compose.dev.yaml",
            "compose.staging.yaml",
            "compose.debug.yaml",
        ):
            text = (REPO / name).read_text()
            for forbidden in (
                "external:",
                "env_file",
                "../",
                "docker.sock",
                "network_mode",
                "include:",
                "extends:",
            ):
                self.assertNotIn(forbidden, text, (name, forbidden))


class ValidatorFailsClosed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if yaml is None:
            raise unittest.SkipTest("PyYAML unavailable on this interpreter")
        cls.dev = oss_env.static_config(DEV, variables(DEV))
        cls.stg = oss_env.static_config(STG, variables(STG))

    def assertRejected(self, base, env, mutate, protected_names=None):
        value = copy.deepcopy(base)
        mutate(value)
        with self.assertRaises(oss_env.IsolationError):
            oss_env.validate_config(value, env, protected_names)

    def test_mutations_are_rejected(self):
        s = "services"
        mutations = {
            "foreign project": lambda c: c.update(name="other-stack"),
            "ci project": lambda c: c.update(name="nextup-ci-0123456789ab"),
            "unnamed volume": lambda c: c["volumes"]["postgres-data"].pop("name"),
            "foreign volume": lambda c: c["volumes"]["postgres-data"].update(
                name="other_postgres-data"
            ),
            "external volume": lambda c: c["volumes"]["redis-data"].update(external=True),
            "undeclared volume": lambda c: c[s]["postgres"]["volumes"].append("other-data:/x"),
            "host bind": lambda c: c[s]["postgres"]["volumes"].append(
                "/srv/data:/var/lib/postgresql/data"
            ),
            "docker socket": lambda c: (
                c[s]["api"].setdefault("volumes", []).append("/var/run/docker.sock:/s")
            ),
            "published db": lambda c: c[s]["postgres"].update(ports=["127.0.0.1:19432:5432"]),
            "published redis": lambda c: c[s]["redis"].update(ports=["127.0.0.1:16379:6379"]),
            "all interfaces": lambda c: c[s]["api"].update(ports=["0.0.0.0:18000:8000"]),
            "legacy port": lambda c: c[s]["api"].update(ports=["127.0.0.1:8000:8000"]),
            "dynamic port": lambda c: c[s]["api"].update(ports=["127.0.0.1::8000"]),
            "foreign image": lambda c: c[s]["api"].update(image="other/backend:local"),
            "unpinned image": lambda c: c[s]["postgres"].update(image="postgres:latest"),
            "container name": lambda c: c[s]["api"].update(container_name="api"),
            "env file": lambda c: c[s]["api"].update(env_file=["../other/.env"]),
            "host network": lambda c: c[s]["api"].update(network_mode="host"),
            "privileged": lambda c: c[s]["worker"].update(privileged=True),
            "legacy DATABASE_URL": lambda c: c[s]["api"]["environment"].update(
                DATABASE_URL="postgresql+psycopg://nextup_dev_app:p@postgres:5432/nextup_dev"
            ),
            "PGOPTIONS in a backend": lambda c: c[s]["api"]["environment"].update(
                PGOPTIONS="-c nextup.provisioning=complete-v1"
            ),
            "PGOPTIONS in migrate": lambda c: c[s]["migrate"]["environment"].update(
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
            "foreign database": lambda c: c[s]["api"]["environment"].update(NEXTUP_DB_NAME="other"),
            "foreign db host": lambda c: c[s]["api"]["environment"].update(
                NEXTUP_DB_HOST="db.example"
            ),
            "foreign db port": lambda c: c[s]["worker"]["environment"].update(
                NEXTUP_DB_PORT="6543"
            ),
            "inline password": lambda c: c[s]["worker"]["environment"].update(
                NEXTUP_DB_PASSWORD="p" * 30
            ),
            "unknown backend key": lambda c: c[s]["api"]["environment"].update(
                NEXTUP_GUARD_DISABLED="1"
            ),
            "runtime as owner": lambda c: c[s]["api"]["environment"].update(
                NEXTUP_DB_USER="nextup_dev_owner"
            ),
            "runtime as migrator": lambda c: c[s]["scheduler"]["environment"].update(
                NEXTUP_DB_ROLE="migrator"
            ),
            "runtime with key path": lambda c: c[s]["worker"]["environment"].update(
                NEXTUP_MIGRATION_KEY_FILE="/run/secrets/migration_key"
            ),
            "runtime owner secret": lambda c: c[s]["api"]["secrets"].append("db_owner_password"),
            "runtime admin secret": lambda c: c[s]["worker"]["secrets"].append("db_admin_password"),
            "runtime migration key": lambda c: c[s]["scheduler"]["secrets"].append("migration_key"),
            "runtime wrong secret path": lambda c: c[s]["api"].update(
                secrets=[{"source": "db_app_password", "target": "/tmp/pw"}]
            ),
            "runtime other env": lambda c: c[s]["api"]["environment"].update(NEXTUP_ENV="staging"),
            "runtime bad instance": lambda c: c[s]["api"]["environment"].update(
                NEXTUP_INSTANCE_ID="1"
            ),
            "runtime as root": lambda c: c[s]["api"].update(user="0:0"),
            "runtime restarts": lambda c: c[s]["worker"].update(restart="always"),
            "runtime entrypoint override": lambda c: c[s]["api"].update(entrypoint=["uvicorn"]),
            "frontend secret": lambda c: c[s]["frontend"].update(secrets=["db_app_password"]),
            "frontend db settings": lambda c: c[s]["frontend"].update(
                environment={"NEXTUP_DB_USER": "x"}
            ),
            "postgres init db": lambda c: c[s]["postgres"]["environment"].update(
                POSTGRES_DB="nextup_dev"
            ),
            "postgres inline password": lambda c: c[s]["postgres"]["environment"].update(
                POSTGRES_PASSWORD="p" * 30
            ),
            "postgres app as superuser": lambda c: c[s]["postgres"]["environment"].update(
                POSTGRES_USER="nextup_dev_app"
            ),
            "postgres extra env": lambda c: c[s]["postgres"]["environment"].update(
                PGHOST="elsewhere"
            ),
            "no cluster_name": lambda c: c[s]["postgres"].update(command=["postgres"]),
            "foreign cluster_name": lambda c: c[s]["postgres"].update(
                command=["postgres", "-c", "cluster_name=main"]
            ),
            "writable init scripts": lambda c: c[s]["postgres"].update(
                volumes=[v.replace(":ro", "") for v in c[s]["postgres"]["volumes"]]
            ),
            "no init tmpfs": lambda c: c[s]["postgres"].pop("tmpfs"),
            "noisy postgres entrypoint": lambda c: c[s]["postgres"]["entrypoint"].__setitem__(
                2, c[s]["postgres"]["entrypoint"][2] + "cat /run/secrets/db_admin_password\n"
            ),
            "image entrypoint skipped": lambda c: c[s]["postgres"].update(entrypoint=["postgres"]),
            "postgres lacks owner secret": lambda c: c[s]["postgres"]["secrets"].remove(
                "db_owner_password"
            ),
            "secret from environment": lambda c: c["secrets"]["db_app_password"].update(
                environment="X"
            ),
            "secret outside .secrets": lambda c: c["secrets"]["db_app_password"].update(
                file="./elsewhere/db_app_password"
            ),
            "secret renamed": lambda c: c["secrets"]["db_app_password"].update(
                file="./.secrets/dev/other"
            ),
            "external secret": lambda c: c["secrets"].update(extra={"external": True}),
            "missing secret": lambda c: c["secrets"].pop("migration_key"),
            "google token": lambda c: c[s]["scheduler"]["environment"].update(
                NEXTUP_GMAIL_REFRESH_TOKEN="t"
            ),
            "google token file": lambda c: c[s]["scheduler"]["environment"].update(
                NEXTUP_GMAIL_REFRESH_TOKEN_FILE="/run/secrets/x"
            ),
            "gmail sync": lambda c: c[s]["worker"]["environment"].update(
                NEXTUP_GMAIL_SYNC_ENABLED="true"
            ),
            "live fetch": lambda c: c[s]["worker"]["environment"].update(
                NEXTUP_LIVE_JOB_FETCH_ENABLED="true"
            ),
            "classifier": lambda c: c[s]["worker"]["environment"].update(
                NEXTUP_EXTERNAL_CLASSIFIER_ENABLED="true"
            ),
            "fixtures": lambda c: c[s]["api"]["environment"].update(
                NEXTUP_FIXTURE_DATA_MODE="true"
            ),
            "awaits migrate": lambda c: c[s]["api"]["depends_on"].update(migrate={}),
            "migrate enabled": lambda c: c[s]["migrate"].update(
                entrypoint=["alembic"], command=["upgrade", "head"]
            ),
            "migrate applies by default": lambda c: c[s]["migrate"].update(
                command=["apply", "--token", "x"]
            ),
            "migrate shell entrypoint": lambda c: c[s]["migrate"].update(
                entrypoint=["/bin/sh", "-c", "alembic upgrade head"]
            ),
            "migrate restarts": lambda c: c[s]["migrate"].update(restart="on-failure"),
            "migrate as app": lambda c: c[s]["migrate"]["environment"].update(
                NEXTUP_DB_USER="nextup_dev_app"
            ),
            "migrate without key": lambda c: c[s]["migrate"]["secrets"].remove("migration_key"),
            "migrate default profile": lambda c: c[s]["migrate"].pop("profiles"),
            "second scheduler": lambda c: c[s]["worker"].update(command=["celery", "beat"]),
            "external network": lambda c: c.setdefault("networks", {}).update(
                default={"external": True}
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label):
                self.assertRejected(self.dev, DEV, mutate)

    def test_staging_specific_rules(self):
        s = "services"
        for label, mutate in {
            "network not internal": lambda c: c["networks"]["backend"].update(internal=False),
            "db on edge": lambda c: c[s]["postgres"].update(networks=["backend", "edge"]),
            "live fetch": lambda c: c[s]["worker"]["environment"].update(
                NEXTUP_LIVE_JOB_FETCH_ENABLED="true"
            ),
            "debug bind": lambda c: (
                c[s]["api"].setdefault("volumes", []).append("./backend/app:/app/app:ro")
            ),
            "dev identity": lambda c: c.update(name="nextup-oss-dev"),
            "dev env inside": lambda c: c[s]["api"]["environment"].update(NEXTUP_ENV="dev"),
            "user override": lambda c: c[s]["api"].update(user="1000:1000"),
            "no secrets group": lambda c: c[s]["worker"].pop("group_add"),
            "root group": lambda c: c[s]["worker"].update(group_add=["0"]),
            "no restart limit": lambda c: c[s]["api"].update(restart="always"),
            "relative secret": lambda c: c["secrets"]["db_app_password"].update(
                file="./secrets/db_app_password"
            ),
            "secret in repository": lambda c: c["secrets"]["db_app_password"].update(
                file=str(REPO / "secrets/db_app_password")
            ),
        }.items():
            with self.subTest(label):
                self.assertRejected(self.stg, STG, mutate)

    def test_private_denylist_is_applied_on_top_of_the_allowlist(self):
        denied = oss_env.load_protected(None)
        for extra in (
            {"ports": frozenset({18000})},
            {"volumes": frozenset({"nextup-oss-dev_redis-data"})},
            {"databases": frozenset({"nextup_dev"})},
            {"db_users": frozenset({"nextup_dev_app"})},
            {"db_users": frozenset({"nextup_dev_admin"})},
        ):
            with self.subTest(extra=extra), self.assertRaises(oss_env.IsolationError):
                oss_env.validate_config(self.dev, DEV, {**denied, **extra})


class EnvTemplates(unittest.TestCase):
    def test_templates_use_only_their_own_keys_and_carry_no_secrets(self):
        for env in (DEV, STG):
            values = oss_env.parse_env_file((REPO / env.example).read_text())
            oss_env.validate_env_values(values, env, require_identity=False)
            self.assertEqual(values[f"{env.prefix}INSTANCE_ID"], "")
            for key in values:
                self.assertFalse(key.endswith(oss_env.SECRET_SUFFIXES), key)
                self.assertNotIn("PASSWORD", key)
            with self.assertRaises(oss_env.IsolationError):
                oss_env.validate_env_values(values, env)

    def test_staging_secrets_directory_must_be_absolute_and_outside_the_repository(self):
        good = variables(STG)
        oss_env.validate_env_values(good, STG)
        for value in ("relative/dir", "/srv/../etc", str(REPO), str(REPO / "x"), "${HOME}/s", ""):
            with self.subTest(value=value), self.assertRaises(oss_env.IsolationError):
                oss_env.validate_env_values({**good, "NEXTUP_STG_SECRETS_DIR": value}, STG)

    def test_legacy_example_carries_no_settings(self):
        self.assertEqual(oss_env.parse_env_file((REPO / ".env.example").read_text()), {})

    def test_env_parser_rejects_ambiguity(self):
        for text in ("A=1\nA=2\n", "export NEXTUP_DEV_API_PORT=1\n", "lower=1\n", "NOEQUALS\n"):
            with self.subTest(text=text), self.assertRaises(oss_env.IsolationError):
                oss_env.parse_env_file(text)

    def test_protected_list_must_live_outside_the_repository(self):
        with self.assertRaises(oss_env.IsolationError):
            oss_env.load_protected(REPO / "env/dev.env.example")


class EditorAndReferences(unittest.TestCase):
    def tasks(self):
        return json.loads((REPO / ".vscode/tasks.json").read_text())["tasks"]

    def test_tasks_use_only_safe_scripts(self):
        allowed = {
            ("python3", "scripts/local.py"),
            ("python3", "-m"),
            ("bash", "scripts/verify.sh"),
        }
        for task in self.tasks():
            with self.subTest(task=task["label"]):
                self.assertNotIn("runOptions", task)
                if task["type"] == "shell":
                    self.assertNotIn("docker", task["command"])
                    self.assertNotIn("5173", task["command"])
                    self.assertEqual(
                        task["options"]["env"]["API_PROXY_TARGET"], "http://127.0.0.1:18000"
                    )
                    continue
                self.assertIn((task["command"], task["args"][0]), allowed)
                if task["args"][0] == "scripts/local.py":
                    self.assertEqual(task["args"][1:3], ["--env", "dev"])
                    self.assertNotIn("migrate", task["args"])
                    self.assertNotIn("staging", task["args"])
                text = json.dumps(task)
                for forbidden in ("docker", "alembic", "compose.yaml", ".env", "verify_ci.py"):
                    self.assertNotIn(forbidden, text)

    def test_launch_configs_never_start_services(self):
        debug = raw("compose.debug.yaml") if yaml else None
        for config in json.loads((REPO / ".vscode/launch.json").read_text())["configurations"]:
            with self.subTest(config=config["name"]):
                self.assertNotIn("preLaunchTask", config)
                self.assertNotIn("postDebugTask", config)
                if "connect" in config:
                    self.assertEqual(config["connect"]["host"], "127.0.0.1")
                    if debug:
                        published = {
                            p.split(":")[1] for s in debug["services"].values() for p in s["ports"]
                        }
                        self.assertIn(str(config["connect"]["port"]), published)
                if "url" in config:
                    self.assertEqual(config["url"], "http://127.0.0.1:15173")

    def test_referenced_files_exist_and_excluded_docs_are_not_required(self):
        import local

        refused_overrides = set(local.OVERRIDE_FILES)
        for name in (
            "scripts/local.py",
            "scripts/verify.sh",
            "scripts/verify_ci.py",
            "compose.base.yaml",
            "compose.dev.yaml",
            "compose.staging.yaml",
            "compose.debug.yaml",
            "compose.ci.yaml",
            "env/dev.env.example",
            "env/staging.env.example",
            ".env.example",
        ):
            self.assertTrue((REPO / name).is_file(), name)
        for name in (
            "scripts/local.py",
            "scripts/check_config.py",
            "scripts/verify.sh",
            "scripts/verify_failures.py",
            ".vscode/tasks.json",
            ".vscode/launch.json",
        ):
            text = (REPO / name).read_text()
            # Tooling may only mention documents and Compose files that exist in this
            # repository, or override files that the launcher names in order to refuse them.
            for reference in sorted(set(re.findall(r"[\w./-]+\.md\b", text))):
                self.assertTrue((REPO / reference).is_file(), (name, reference))
            for reference in sorted(set(re.findall(r"\b[\w-]*compose[\w.-]*\.ya?ml\b", text))):
                known = (REPO / reference).is_file() or reference in refused_overrides
                self.assertTrue(known, (name, reference))


@needs_yaml
class LibpqVariables(unittest.TestCase):
    """The launcher applies the backend's rule to the shell and to every service."""

    def test_rule_matches_the_backend_loader(self):
        backend = (REPO / "backend/app/config.py").read_text()
        pattern = 'LIBPQ_VARIABLE = re.compile(r"^PG[A-Z][A-Z0-9_]*$")'
        self.assertIn(pattern, backend)
        self.assertIn(pattern, (REPO / "scripts/oss_env.py").read_text())
        self.assertIn('SERVER_ONLY_VARIABLES = frozenset({"PGDATA"})', backend)
        self.assertEqual(oss_env.SERVER_ONLY_VARIABLES, frozenset({"PGDATA"}))

    def test_names(self):
        names = ["PGHOSTADDR", "PGSERVICE", "PGDATA", "PG_MAJOR", "pghost", "XPGHOST", "PGNEW"]
        client = ["PGHOSTADDR", "PGNEW", "PGSERVICE"]
        self.assertEqual(oss_env.libpq_names([*names, "PATH"]), ["PGDATA", *client])
        self.assertEqual(oss_env.libpq_names(names, server=True), client)

    def test_shell_variables_are_refused_by_name_only(self):
        clean = {"PATH": "/usr/bin:/bin", "HOME": "/tmp"}
        oss_env.check_process_environment({**clean, "PGDATA": "/var/lib/postgresql/data"})
        for name in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGSYSCONFDIR", "PGPORT", "PGTZ"):
            with self.subTest(name=name), self.assertRaises(oss_env.IsolationError) as caught:
                oss_env.check_process_environment({**clean, name: "SENTINEL-value"})
            self.assertIn(name, str(caught.exception))
            self.assertNotIn("SENTINEL-value", str(caught.exception))

    def test_server_data_directory_is_accepted_only_on_postgres(self):
        for env in (DEV, STG):
            env_name = env.name
            config = oss_env.static_config(env, variables(env))
            config["services"]["postgres"]["environment"]["PGDATA"] = "/var/lib/postgresql/data"
            oss_env.validate_config(config, env, protected())
            for service in sorted(set(config["services"]) - {"postgres"}):
                damaged = copy.deepcopy(config)
                damaged["services"][service].setdefault("environment", {})
                if isinstance(damaged["services"][service]["environment"], list):
                    damaged["services"][service]["environment"].append("PGDATA=/x")
                else:
                    damaged["services"][service]["environment"]["PGDATA"] = "/x"
                with self.subTest(env=env_name, service=service):
                    with self.assertRaisesRegex(oss_env.IsolationError, "PGDATA"):
                        oss_env.validate_config(damaged, env, protected())


if __name__ == "__main__":
    unittest.main()
