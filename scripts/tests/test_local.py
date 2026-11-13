"""The OSS launcher selects one environment explicitly and fails closed; all mocked."""

import json
import os
import re
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import local
import oss_env
from test_ci import config
from verify_recovery import normalize_schema, snapshot, verify_recovery

REPO = Path(__file__).resolve().parents[2]
CLEAN = {"PATH": "/usr/bin:/bin", "HOME": "/tmp"}
INSTANCE = "3f1c9a52-6a2e-4b7d-9c1e-2d4f6a8b0c1e"
SENTINEL = "SENTINEL_secret_value_never_printed_7c2"


def workspace(directory):
    """A temporary copy of the files the launcher requires, outside the repository."""
    root = Path(directory)
    for name in (
        "compose.base.yaml",
        "compose.dev.yaml",
        "compose.staging.yaml",
        "compose.debug.yaml",
        "scripts/oss_env.py",
        "env/dev.env.example",
        "env/staging.env.example",
        f"{oss_env.INIT_SCRIPT_DIR}/10-nextup-roles.sh",
    ):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / name, root / name)
    return root


def rendered_dev(root="/x", instance=INSTANCE, user="1000:1000"):
    """The shape `docker compose config --format json` returns for a valid dev stack."""
    common = {
        "NEXTUP_ENV": "dev",
        "NEXTUP_INSTANCE_ID": instance,
        "NEXTUP_DB_HOST": "postgres",
        "NEXTUP_DB_PORT": "5432",
        "NEXTUP_DB_NAME": "nextup_dev",
        "NEXTUP_REDIS_URL": "redis://redis:6379/0",
        "NEXTUP_DIAGNOSTIC_INTERVAL_SECONDS": "60",
        **{flag: "false" for flag in oss_env.INTEGRATION_FLAGS},
    }
    runtime_env = {
        **common,
        "NEXTUP_DB_USER": "nextup_dev_app",
        "NEXTUP_DB_PASSWORD_FILE": "/run/secrets/db_app_password",
    }
    migrate_env = {
        **common,
        "NEXTUP_DB_ROLE": "migrator",
        "NEXTUP_DB_USER": "nextup_dev_owner",
        "NEXTUP_DB_PASSWORD_FILE": "/run/secrets/db_owner_password",
        "NEXTUP_MIGRATION_KEY_FILE": "/run/secrets/migration_key",
    }

    def secrets(*names):
        return [{"source": n, "target": f"/run/secrets/{n}"} for n in names]

    def port(published, target):
        return [{"host_ip": "127.0.0.1", "published": str(published), "target": target}]

    backend = {
        "build": {"context": "backend"},
        "image": "nextup-oss-dev/backend:local",
        "user": user,
    }
    runtime = {
        **backend,
        "environment": runtime_env,
        "secrets": secrets("db_app_password"),
        "restart": "no",
    }
    services = {
        "postgres": {
            "image": "postgres:17-bookworm",
            "command": ["postgres", "-c", "cluster_name=nextup-oss-dev"],
            "entrypoint": [
                "/bin/sh",
                "-ec",
                'install -d /run/nextup-initdb\nexec docker-entrypoint.sh "$@"\n',
                "nextup-initdb-wrapper",
            ],
            "environment": {
                "POSTGRES_USER": "nextup_dev_admin",
                "POSTGRES_DB": "postgres",
                "POSTGRES_PASSWORD_FILE": "/run/secrets/db_admin_password",
            },
            "secrets": secrets("db_admin_password", "db_owner_password", "db_app_password"),
            "tmpfs": ["/run/nextup-initdb:mode=0700,size=65536"],
            "volumes": [
                {"type": "volume", "source": "postgres-data", "target": "/var/lib/postgresql/data"},
                {
                    "type": "bind",
                    "source": f"{root}/backend/docker/initdb",
                    "target": "/docker-entrypoint-initdb.d",
                    "read_only": True,
                },
            ],
        },
        "redis": {
            "image": "redis:7.4-bookworm",
            "volumes": [{"type": "volume", "source": "redis-data", "target": "/data"}],
        },
        "migrate": {
            **backend,
            "environment": migrate_env,
            "secrets": secrets("db_owner_password", "migration_key"),
            "profiles": ["migrate"],
            "entrypoint": ["python", "-m", "app.guard"],
            "command": ["plan"],
            "restart": "no",
            "depends_on": {"postgres": {"condition": "service_healthy"}},
        },
        "api": {**runtime, "ports": port(18000, 8000), "depends_on": {"postgres": {}, "redis": {}}},
        "worker": {**runtime, "command": ["celery", "worker"]},
        "scheduler": {
            **runtime,
            "command": ["celery", "beat"],
            "volumes": [{"type": "volume", "source": "scheduler-data", "target": "/state"}],
        },
        "frontend": {
            "build": {"context": "frontend"},
            "image": "nextup-oss-dev/frontend:local",
            "ports": port(15173, 5173),
        },
    }
    volumes = {
        k: {"name": f"nextup-oss-dev_{k}"}
        for k in ("postgres-data", "redis-data", "scheduler-data")
    }
    top = {
        n: {"name": f"nextup-oss-dev_{n}", "file": f"{root}/.secrets/dev/{n}"}
        for n in oss_env.SECRET_NAMES
    }
    return {"name": "nextup-oss-dev", "services": services, "volumes": volumes, "secrets": top}


class RenderedShape(unittest.TestCase):
    def test_docker_long_form_render_is_accepted(self):
        oss_env.validate_config(rendered_dev(), oss_env.ENVIRONMENTS["dev"])

    def test_privileged_secrets_never_reach_runtime_services(self):
        """Acceptance 3 on the rendered (long-form) shape."""
        for service in ("api", "worker", "scheduler"):
            for secret in ("db_owner_password", "db_admin_password", "migration_key"):
                value = rendered_dev()
                value["services"][service]["secrets"].append(
                    {"source": secret, "target": f"/run/secrets/{secret}"}
                )
                with (
                    self.subTest(service=service, secret=secret),
                    self.assertRaises(oss_env.IsolationError),
                ):
                    oss_env.validate_config(value, oss_env.ENVIRONMENTS["dev"])

    def test_validation_errors_never_echo_values(self):
        for mutate in (
            lambda c: c["services"]["api"]["environment"].update(NEXTUP_DB_HOST=SENTINEL),
            lambda c: c["services"]["api"]["environment"].update(NEXTUP_DB_PASSWORD=SENTINEL),
            lambda c: c["services"]["postgres"]["environment"].update(POSTGRES_PASSWORD=SENTINEL),
            lambda c: c["secrets"]["db_app_password"].update(environment=SENTINEL),
        ):
            value = rendered_dev()
            mutate(value)
            with self.assertRaises(oss_env.IsolationError) as caught:
                oss_env.validate_config(value, oss_env.ENVIRONMENTS["dev"])
            self.assertNotIn(SENTINEL, str(caught.exception))


class EnvironmentSelection(unittest.TestCase):
    def test_environment_is_required_and_unknown_names_fail(self):
        with patch("sys.stderr"), self.assertRaises(SystemExit):
            local.parse_args(["start"])
        with patch("sys.stderr"), self.assertRaises(SystemExit):
            local.parse_args(["--env", "prod", "start"])
        with self.assertRaises(oss_env.IsolationError):
            local.LocalStack("production", environ=CLEAN)

    def test_command_names_project_env_file_and_files_explicitly(self):
        stack = local.LocalStack("dev", root=Path("/x"), environ=CLEAN)
        self.assertEqual(
            stack.command[:4], ["docker", "compose", "--project-name", "nextup-oss-dev"]
        )
        self.assertEqual(stack.command[4:6], ["--env-file", "/x/.env.dev"])
        self.assertEqual(
            stack.command[6:], ["-f", "/x/compose.base.yaml", "-f", "/x/compose.dev.yaml"]
        )
        self.assertNotIn("/x/compose.yaml", stack.command)

    def test_debug_overlay_is_dev_only(self):
        stack = local.LocalStack("dev", root=Path("/x"), environ=CLEAN, debug=True)
        self.assertEqual(stack.command[-1], "/x/compose.debug.yaml")
        with self.assertRaises(oss_env.IsolationError):
            local.LocalStack("staging", root=Path("/x"), environ=CLEAN, debug=True)

    def test_project_overrides_in_the_shell_are_refused_not_ignored(self):
        for key in (
            "COMPOSE_PROJECT_NAME",
            "COMPOSE_FILE",
            "COMPOSE_PROFILES",
            "COMPOSE_ENV_FILES",
        ):
            with self.subTest(key=key), self.assertRaises(oss_env.IsolationError):
                local.LocalStack("dev", environ={**CLEAN, key: "other-stack"})

    def test_environment_settings_in_the_shell_are_refused(self):
        with self.assertRaisesRegex(oss_env.IsolationError, "NEXTUP_DEV_INSTANCE_ID"):
            local.LocalStack("dev", environ={**CLEAN, "NEXTUP_DEV_INSTANCE_ID": INSTANCE})

    def test_unsupported_overrides_and_foreign_credentials_are_refused(self):
        """Acceptance 7: application settings, identity overrides, the raw-Compose tripwire
        and legacy credentials in the shell are refused by name, not silently dropped."""
        for key in (
            "NEXTUP_ENV",
            "NEXTUP_DB_NAME",
            "NEXTUP_DB_USER",
            "NEXTUP_DB_HOST",
            "NEXTUP_MIGRATION_KEY_FILE",
            "NEXTUP_RAW_COMPOSE_IS_DISABLED",
            "NEXTUP_GUARD_DISABLED",
            "DATABASE_URL",
            "POSTGRES_PASSWORD",
            "PGPASSWORD",
            "PGOPTIONS",  # client session options are refused, never passed on
            # every PostgreSQL client variable, known or not
            "PGHOSTADDR",
            "PGPORT",
            "PGSERVICE",
            "PGSYSCONFDIR",
            "PGSSLMODE",
            "PGNEWTHING",
            "GMAIL_REFRESH_TOKEN",
            "N8N_API_KEY",
        ):
            with self.subTest(key=key):
                with self.assertRaises(oss_env.IsolationError) as caught:
                    local.LocalStack("dev", environ={**CLEAN, key: SENTINEL})
                self.assertIn(key, str(caught.exception))
                self.assertNotIn(SENTINEL, str(caught.exception))
        local.LocalStack("dev", environ={**CLEAN, oss_env.PROTECTED_FILE_VARIABLE: ""})

    def test_shell_values_never_reach_compose(self):
        environ = {
            **CLEAN,
            "DOCKER_CONTEXT": "default",
            "AWS_SECRET_ACCESS_KEY": SENTINEL,
            "SSH_AUTH_SOCK": "/s",
        }
        stack = local.LocalStack("dev", environ=environ)
        self.assertEqual(
            stack.process_env,
            {"PATH": "/usr/bin:/bin", "HOME": "/tmp", "DOCKER_CONTEXT": "default"},
        )

    def test_compose_override_files_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = workspace(directory)
            (root / "compose.override.yaml").write_text("services: {}\n")
            stack = local.LocalStack("dev", root=root, environ=CLEAN)
            stack.compose = MagicMock()
            with self.assertRaisesRegex(oss_env.IsolationError, "override"):
                stack.check_layout()
            stack.compose.assert_not_called()

    def test_protected_identities_are_refused(self):
        denied = {**oss_env.load_protected(None), "db_users": frozenset({"nextup_dev_app"})}
        with self.assertRaises(oss_env.IsolationError):
            oss_env.validate_config(rendered_dev(), oss_env.ENVIRONMENTS["dev"], denied)
        denied = {**oss_env.load_protected(None), "db_users": frozenset({"nextup_dev_admin"})}
        with self.assertRaises(oss_env.IsolationError):
            oss_env.validate_config(rendered_dev(), oss_env.ENVIRONMENTS["dev"], denied)

    def test_staging_requires_typed_confirmation_before_anything_runs(self):
        with patch.object(local, "LocalStack") as stack, patch("sys.stderr"):
            self.assertEqual(local.main(["--env", "staging", "start"]), 1)
            self.assertEqual(
                local.main(["--env", "staging", "--confirm-project", "nextup-oss-dev", "start"]), 1
            )
        stack.assert_not_called()


PLAN_LINES = [
    "nextup-guard: PLAN mode=INIT env=dev database=nextup_dev from=empty to=0029 steps=29",
    "nextup-guard: steps: 0001, ..., 0029",
    "nextup-guard: data-changing steps: 0004, 0019, 0025, 0027, 0029",
    "nextup-guard: confirmation=0123456789ab expires_in=600s single-use",
    "nextup-guard: awaiting confirmation",
]
APPLIED = ["nextup-guard: APPLIED mode=INIT to=0029 env=dev"]


class Migration(unittest.TestCase):
    """`guard plan-apply`: the launcher relays the operator's typed code and
    never receives, prints or forwards an authorization token."""

    def stack(self):
        stack = local.LocalStack("dev", environ=CLEAN)
        stack.doctor = MagicMock()
        stack.compose = MagicMock(return_value="")
        return stack

    def session(self, lines=PLAN_LINES, after=APPLIED, returncode=0, awaited=True):
        calls = {}

        def plan_apply(command, *, decide, cwd, env, timeout):
            calls.update(command=command, env=env)
            session = local.guard_session.Session(lines=list(lines), awaited=awaited)
            if awaited:
                session.code = "0123456789ab"
                calls["answer"] = decide(list(lines), session.code)
                session.confirmed = calls["answer"] is not None
                session.lines += after if session.confirmed else ["nextup-guard: REFUSE NXG-A11"]
                session.returncode = returncode if session.confirmed else 3
            else:
                session.returncode = returncode
            return session

        return calls, plan_apply

    def test_staging_migrate_is_refused_without_touching_docker(self):
        with (
            patch.object(local.subprocess, "run") as run,
            patch.object(local, "LocalStack") as stack,
            patch("sys.stderr"),
        ):
            self.assertEqual(
                local.main(["--env", "staging", "--confirm-project", "nextup-oss-stg", "migrate"]),
                local.MIGRATION_REFUSED_EXIT,
            )
            self.assertEqual(
                local.main(["--env", "staging", "migrate"]), local.MIGRATION_REFUSED_EXIT
            )
        run.assert_not_called()
        stack.assert_not_called()
        with self.assertRaises(oss_env.IsolationError):
            local.LocalStack("staging", environ=CLEAN).migrate(
                prompt=lambda _: "x", interactive=True
            )

    def test_dev_migrate_needs_a_terminal(self):
        stack = self.stack()
        with self.assertRaisesRegex(RuntimeError, "interactive terminal"):
            stack.migrate(prompt=lambda _: "0123456789ab", interactive=False)
        stack.compose.assert_not_called()
        stack.doctor.assert_not_called()

    def test_plan_is_shown_and_only_the_typed_code_confirms(self):
        for typed in ("", "yes", "0123456789AB", "0123456789a"):
            stack = self.stack()
            calls, fake = self.session()
            with (
                patch.object(local.guard_session, "plan_apply", fake),
                patch("builtins.print") as printed,
            ):
                stack.migrate(prompt=lambda _, typed=typed: typed, interactive=True)
            self.assertIsNone(calls["answer"], typed)  # declined: stdin closed, nothing applied
            shown = " ".join(str(c.args[0]) for c in printed.call_args_list)
            self.assertIn("mode=INIT", shown)
            self.assertIn("Cancelled; nothing was applied.", shown)
        stack = self.stack()
        calls, fake = self.session()
        with (
            patch.object(local.guard_session, "plan_apply", fake),
            patch("builtins.print") as printed,
        ):
            stack.migrate(prompt=lambda _: "0123456789ab", interactive=True)
        self.assertEqual(calls["answer"], "0123456789ab")
        self.assertEqual(
            calls["command"],
            [*stack.command, "--profile", "migrate", "run", "--rm", "-T", "migrate", "plan-apply"],
        )
        self.assertFalse(any("nxa1." in part or "token" in part for part in calls["command"]))
        self.assertNotIn("nxa1.", json.dumps(calls["env"]))
        shown = " ".join(str(c.args[0]) for c in printed.call_args_list)
        self.assertIn("APPLIED mode=INIT", shown)
        self.assertNotIn("awaiting confirmation", shown)

    def test_nothing_to_apply(self):
        stack = self.stack()
        lines = [
            "nextup-guard: PLAN mode=NOOP env=dev database=nextup_dev from=0029 to=0029 steps=0",
            "nextup-guard: nothing to apply",
        ]
        _, fake = self.session(lines=lines, awaited=False)
        prompt = MagicMock()
        with (
            patch.object(local.guard_session, "plan_apply", fake),
            patch("builtins.print") as printed,
        ):
            stack.migrate(prompt=prompt, interactive=True)
        prompt.assert_not_called()
        self.assertIn("Nothing to apply.", [c.args[0] for c in printed.call_args_list])

    def test_refusals_surface_only_guard_lines(self):
        for lines, after, awaited in (
            ([f"Traceback {SENTINEL}", "nextup-guard: REFUSE NXG-I04 wrong role"], [], False),
            (PLAN_LINES, [f"driver text {SENTINEL}", "nextup-guard: REFUSE NXG-A04 expired"], True),
        ):
            stack = self.stack()
            _, fake = self.session(lines=lines, after=after, returncode=3, awaited=awaited)
            with (
                self.subTest(lines=lines[-1]),
                patch.object(local.guard_session, "plan_apply", fake),
                patch("builtins.print") as printed,
                self.assertRaises(RuntimeError) as caught,
            ):
                stack.migrate(prompt=lambda _: "0123456789ab", interactive=True)
            text = str(caught.exception) + " ".join(str(c.args) for c in printed.call_args_list)
            self.assertIn("NXG-", text)
            self.assertNotIn(SENTINEL, text)

    def test_missing_docker_is_reported_plainly(self):
        stack = self.stack()
        with (
            patch.object(
                local.guard_session, "plan_apply", side_effect=FileNotFoundError("docker")
            ),
            self.assertRaisesRegex(RuntimeError, "Missing executable"),
        ):
            stack.migrate(prompt=lambda _: "x", interactive=True)

    def test_guard_refusal_lines_are_surfaced_but_nothing_else(self):
        error = local.subprocess.CalledProcessError(
            3,
            ["docker"],
            output=f"stdout {SENTINEL}",
            stderr=(
                f"Traceback {SENTINEL}\n"
                "nextup-guard: REFUSE NXG-M01 database is populated but has no environment marker\n"
            ),
        )
        stack = local.LocalStack("dev", environ=CLEAN)
        with patch.object(local.subprocess, "run", side_effect=error):
            with self.assertRaises(RuntimeError) as caught:
                stack.run(["docker", "compose", "run"])
        self.assertIn("NXG-M01", str(caught.exception))
        self.assertNotIn(SENTINEL, str(caught.exception))

    def test_no_action_issues_down_or_volume_removal(self):
        source = (REPO / "scripts/local.py").read_text()
        for forbidden in ('"down"', "'down'", "--volumes", '"-v"', "volume rm", "prune"):
            self.assertNotIn(forbidden, source)

    def test_never_calls_alembic(self):
        """T-UNIT-02e: migrations only through the guard's plan/apply."""
        self.assertNotIn("alembic", (REPO / "scripts/local.py").read_text())


class PrivateEnvFiles(unittest.TestCase):
    def test_reads_only_its_own_environment_file(self):
        """T-UNIT-02f: never `.env` or another stack's env file."""
        for name in ("dev", "staging"):
            stack = local.LocalStack(name, root=Path("/x"), environ=CLEAN)
            self.assertEqual(stack.env_file, Path("/x") / f".env.{name}")
        source = (REPO / "scripts/local.py").read_text()
        self.assertIsNone(re.search(r"""["']\.env["']""", source))
        self.assertNotIn(
            "..", "".join(oss_env.ENVIRONMENTS[n].env_file for n in ("dev", "staging"))
        )


def valid_env_text(**overrides):
    values = {
        "NEXTUP_DEV_INSTANCE_ID": INSTANCE,
        "NEXTUP_DEV_LOCAL_UID": "1000",
        "NEXTUP_DEV_LOCAL_GID": "1000",
    }
    values.update(overrides)
    return "".join(f"{k}={v}\n" for k, v in values.items() if v is not None)


class StartAndEnvFile(unittest.TestCase):
    def stack(self, root):
        stack = local.LocalStack("dev", root=root, environ=CLEAN)
        stack.check_tools = MagicMock()
        stack.status = MagicMock()
        stack.compose = MagicMock(
            side_effect=lambda *a, **k: json.dumps(rendered_dev(str(root))) if "config" in a else ""
        )
        return stack

    def test_first_start_generates_private_env_and_secrets_validates_then_starts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = workspace(directory)
            stack = self.stack(root)
            with patch("builtins.print") as printed:
                stack.start()
            env_file = root / ".env.dev"
            self.assertEqual(env_file.stat().st_mode & 0o777, 0o600)
            values = oss_env.parse_env_file(env_file.read_text())
            oss_env.validate_env_values(values, oss_env.ENVIRONMENTS["dev"])
            self.assertEqual(values["NEXTUP_DEV_LOCAL_UID"], str(os.getuid()))
            self.assertEqual(uuid.UUID(values["NEXTUP_DEV_INSTANCE_ID"]).version, 4)
            self.assertFalse(any(k.endswith(oss_env.SECRET_SUFFIXES) for k in values))
            directory_mode = (root / ".secrets/dev").stat().st_mode & 0o777
            self.assertEqual(directory_mode, 0o700)
            secrets = {}
            for name in oss_env.SECRET_NAMES:
                path = root / ".secrets/dev" / name
                self.assertEqual(path.stat().st_mode & 0o777, 0o600, name)
                secrets[name] = path.read_text().strip()
            self.assertEqual(len(set(secrets.values())), 4)
            shown = " ".join(str(c.args[0]) for c in printed.call_args_list)
            self.assertFalse(any(value in shown for value in secrets.values()))
            calls = [c.args for c in stack.compose.call_args_list]
            self.assertIn("config", calls[0])
            self.assertEqual(calls[1], ("up", "--build", "--wait", "--wait-timeout", "180"))
            # start never migrates: no `run ... migrate`, no plan, no apply
            # (the render may name the profile)
            self.assertFalse(any("run" in c or "plan" in c or "apply" in c for c in calls))
            self.assertEqual(len(calls), 2)

    def test_two_workspaces_never_share_generated_values(self):
        seen = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as directory:
                root = workspace(directory)
                with patch("builtins.print"):
                    self.stack(root).start()
                seen.append(
                    oss_env.parse_env_file((root / ".env.dev").read_text())[
                        "NEXTUP_DEV_INSTANCE_ID"
                    ]
                )
                seen.extend((root / ".secrets/dev" / n).read_text() for n in oss_env.SECRET_NAMES)
        self.assertEqual(len(set(seen)), len(seen))

    def test_existing_env_file_and_secrets_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = workspace(directory)
            original = valid_env_text()
            (root / ".env.dev").write_text(original)
            os.chmod(root / ".env.dev", 0o600)
            with patch("builtins.print"):
                self.stack(root).start()
            before = {n: (root / ".secrets/dev" / n).read_text() for n in oss_env.SECRET_NAMES}
            with patch("builtins.print"):
                self.stack(root).start()
            self.assertEqual((root / ".env.dev").read_text(), original)
            self.assertEqual(
                {n: (root / ".secrets/dev" / n).read_text() for n in oss_env.SECRET_NAMES}, before
            )

    def test_unsafe_env_files_stop_before_compose(self):
        cases = {
            "foreign key": valid_env_text(POSTGRES_PASSWORD="k" * 32),
            "password in env file": valid_env_text(NEXTUP_DEV_POSTGRES_PASSWORD="k" * 32),
            "missing instance": valid_env_text(NEXTUP_DEV_INSTANCE_ID=None),
            "not uuid4": valid_env_text(
                NEXTUP_DEV_INSTANCE_ID="00000000-0000-1000-8000-000000000000"
            ),
            "root uid": valid_env_text(NEXTUP_DEV_LOCAL_UID="0"),
            "staging key": valid_env_text(NEXTUP_STG_API_PORT="28000"),
            "legacy port": valid_env_text(NEXTUP_DEV_API_PORT="8000"),
            "identity override": valid_env_text(NEXTUP_DEV_DB_NAME="other"),
        }
        for label, text in cases.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as directory:
                root = workspace(directory)
                (root / ".env.dev").write_text(text)
                os.chmod(root / ".env.dev", 0o600)
                stack = self.stack(root)
                with patch("builtins.print"), self.assertRaises(oss_env.IsolationError):
                    stack.start()
                stack.compose.assert_not_called()

    def test_unsafe_secret_files_stop_before_compose(self):
        def loosen(root):
            os.chmod(root / ".secrets/dev/db_app_password", 0o640)

        def symlink(root):
            target = root / "elsewhere"
            target.write_text("x" * 40 + "\n")
            (root / ".secrets/dev/migration_key").unlink()
            (root / ".secrets/dev/migration_key").symlink_to(target)

        def open_directory(root):
            os.chmod(root / ".secrets/dev", 0o750)

        def duplicate(root):
            shutil.copy(
                root / ".secrets/dev/db_owner_password", root / ".secrets/dev/db_app_password"
            )

        def placeholder(root):
            (root / ".secrets/dev/db_admin_password").write_text("changeme\n")

        for label, damage in {
            "group-readable file": loosen,
            "symlink": symlink,
            "open directory": open_directory,
            "duplicate values": duplicate,
            "weak value": placeholder,
        }.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as directory:
                root = workspace(directory)
                with patch("builtins.print"):
                    self.stack(root).start()
                damage(root)
                stack = self.stack(root)
                with patch("builtins.print"), self.assertRaises(oss_env.IsolationError) as caught:
                    stack.start()
                stack.compose.assert_not_called()
                for name in oss_env.SECRET_NAMES:
                    path = root / ".secrets/dev" / name
                    if path.is_file() and not path.is_symlink():
                        self.assertNotIn(path.read_text().strip(), str(caught.exception))

    def test_world_readable_or_symlinked_env_file_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = workspace(directory)
            (root / ".env.dev").write_text(valid_env_text())
            os.chmod(root / ".env.dev", 0o644)
            with (
                patch("builtins.print"),
                self.assertRaisesRegex(oss_env.IsolationError, "chmod 600"),
            ):
                self.stack(root).start()
            (root / ".env.dev").unlink()
            (root / "elsewhere.env").write_text(valid_env_text())
            (root / ".env.dev").symlink_to(root / "elsewhere.env")
            with patch("builtins.print"), self.assertRaises(oss_env.IsolationError):
                self.stack(root).start()

    def test_staging_env_and_secrets_are_never_generated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = workspace(directory)
            stack = local.LocalStack("staging", root=root, environ=CLEAN)
            stack.check_tools = MagicMock()
            stack.compose = MagicMock()
            with patch("builtins.print"), self.assertRaisesRegex(RuntimeError, "never generated"):
                stack.start()
            self.assertFalse((root / ".env.staging").exists())
            self.assertFalse((root / ".secrets").exists())
            stack.compose.assert_not_called()
            with self.assertRaises(RuntimeError):
                stack.ensure_secrets()

    def test_rendered_config_failing_validation_prevents_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = workspace(directory)
            bad = rendered_dev(str(root))
            bad["services"]["api"]["secrets"].append(
                {"source": "db_owner_password", "target": "/run/secrets/db_owner_password"}
            )
            stack = self.stack(root)
            stack.compose = MagicMock(return_value=json.dumps(bad))
            with patch("builtins.print"), self.assertRaises(oss_env.IsolationError):
                stack.start()
            self.assertEqual(stack.compose.call_count, 1)  # config only, never up

    def test_failed_prerequisite_prevents_env_creation_and_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = workspace(directory)
            stack = self.stack(root)
            stack.check_tools = MagicMock(side_effect=RuntimeError("Docker unavailable"))
            with self.assertRaisesRegex(RuntimeError, "Docker unavailable"):
                stack.start()
            self.assertFalse((root / ".env.dev").exists())
            self.assertFalse((root / ".secrets").exists())
            stack.compose.assert_not_called()

    def test_missing_oss_layout_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            stack = self.stack(Path(directory))
            with self.assertRaisesRegex(RuntimeError, "Expected Nextup OSS workspace"):
                stack.start()
            stack.compose.assert_not_called()

    def test_generated_files_are_created_exclusively(self):
        source = (REPO / "scripts/local.py").read_text()
        self.assertEqual(source.count("os.O_EXCL"), 2)
        self.assertIn("os.O_NOFOLLOW", source)


class StatusAndStop(unittest.TestCase):
    def test_stop_validates_then_stops_without_removing_anything(self):
        stack = local.LocalStack("dev", environ=CLEAN)
        stack.doctor = MagicMock()
        stack.compose = MagicMock(return_value="")
        stack.stop()
        stack.doctor.assert_called_once()
        stack.compose.assert_called_once_with("stop", timeout=120)

    def test_rejects_nonlocal_api_address_before_http(self):
        stack = local.LocalStack("dev", environ=CLEAN)
        stack.compose = MagicMock(side_effect=["running", "0.0.0.0:18000"])
        with patch.object(local.urllib.request, "urlopen") as http:
            with self.assertRaisesRegex(RuntimeError, "localhost"):
                stack.status()
        http.assert_not_called()

    def test_failures_return_nonzero_without_echoing_output(self):
        error = local.subprocess.CalledProcessError(
            1, ["docker"], output="SECRET-OUTPUT", stderr="SECRET-ERR"
        )
        stack = local.LocalStack("dev", environ=CLEAN)
        with patch.object(local.subprocess, "run", side_effect=error):
            with self.assertRaises(RuntimeError) as caught:
                stack.run(["docker", "compose", "config"])
        self.assertNotIn("SECRET", str(caught.exception))

    def test_missing_executable_names_prerequisite(self):
        with patch.object(local.subprocess, "run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(RuntimeError, "Missing executable: docker"):
                local.LocalStack("dev", environ=CLEAN).run(["docker", "version"])


class RecoveryGuards(unittest.TestCase):
    def test_normalizes_only_equivalent_varchar_array_casts(self):
        original = (
            "status = ANY ((ARRAY['queued'::character varying, "
            "'running'::character varying])::text[])"
        )
        restored = (
            "status = ANY (ARRAY[('queued'::character varying)::text, "
            "('running'::character varying)::text])"
        )
        self.assertEqual(normalize_schema(restored), original)
        self.assertEqual(normalize_schema(original), original)
        self.assertNotEqual(normalize_schema(restored.replace("queued", "changed")), original)
        self.assertNotEqual(normalize_schema(restored.replace("status =", "source =")), original)
        other_type = "ARRAY[('1'::integer)::text]"
        self.assertEqual(normalize_schema(other_type), other_type)

    def test_refuses_development_project_before_any_command(self):
        stack = MagicMock(project="nextup-oss-dev")
        with self.assertRaisesRegex(AssertionError, "CI project required"):
            verify_recovery(stack)
        stack.compose.assert_not_called()
        stack.request.assert_not_called()

    def test_rejects_shared_volume_before_writes_or_stops(self):
        value = config()
        value.update(name="nextup-ci-012345abcdef", volumes={"postgres-data": {}})
        stack = MagicMock(project=value["name"])
        stack.compose.return_value = json.dumps(value)
        with self.assertRaises(AssertionError):
            verify_recovery(stack)
        stack.compose.assert_called_once_with(
            "--profile", "test", "--profile", "migrate", "config", "--format", "json"
        )
        stack.request.assert_not_called()

    def test_missing_tables_cannot_count_as_restored(self):
        stack = MagicMock()
        stack.compose.return_value = "profiles"
        with self.assertRaisesRegex(AssertionError, "Unexpected public table set"):
            snapshot(stack, "nextup_ci")


if __name__ == "__main__":
    unittest.main()
