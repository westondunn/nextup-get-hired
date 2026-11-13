"""The 36 CI negative scenarios (N1-N36), repeated statically.

No Docker Engine is used: a static approximation of `docker compose config --format json`
renders compose.ci.yaml (plus the probe overlay), and the candidate's own validator and
launcher preflight judge the result. Every scenario must fail closed (render fails,
validator rejects, or the launcher refuses before any subprocess), except N4, which must
render unchanged and be accepted.

N34 (harness correction): the probe uses this repository's verify_ci (ROOT is this
candidate), and only the repository-boundary refusal counts; any other refusal reason is
a test failure, so a harness artifact can no longer pass as a security refusal.
"""

import copy
import json
import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import oss_env
import verify_ci
from test_ci import REPO, redirected, sandboxed_stacks

try:
    import yaml
except ImportError:  # pragma: no cover - depends on the host interpreter
    yaml = None

PROJECT = "nextup-ci-0123456789ab"
PROTECTED_LOOKING = "other-stack"  # synthetic; the real protected list is never in code
RUN = "/tmp/nextup-ci-1001/nextup-ci-0123456789ab-run"
CI_VARS = {
    "NEXTUP_CI_UID": "1001",
    "NEXTUP_CI_GID": "1001",
    "NEXTUP_CI_SECRETS_DIR": f"{RUN}/secrets",
    "NEXTUP_CI_E2E_DIR": f"{RUN}/e2e",
}
USER = "1001:1001"
HOSTILE = {
    "DATABASE_URL": "postgresql://hostile:hostilePW_n4@elsewhere.invalid/otherdb",
    "POSTGRES_PASSWORD": "hostilePW_n4",
    "NEXTUP_DB_NAME": "otherapp",
    "NEXTUP_DB_USER": "nextup_ci_owner",
    "NEXTUP_DB_HOST": "elsewhere.invalid",
    "NEXTUP_ENV": "staging",
    "NEXTUP_MIGRATION_KEY_FILE": "/run/secrets/x",
    "GMAIL_REFRESH_TOKEN": "hostileTOK_n4",
    "N8N_ENABLED": "true",
    "NEXTUP_TEST_BLOCK": "1",
    "NEXTUP_GMAIL_SYNC_ENABLED": "true",
    "NEXTUP_FIXTURE_DATA_MODE": "false",
    "NEXTUP_LIVE_JOB_FETCH_ENABLED": "true",
}
HOSTILE_MARKERS = ("hostilePW_n4", "hostileTOK_n4", "elsewhere.invalid", "otherapp", "otherdb")


class RenderFailed(Exception):
    pass


def _ports(service):
    result = []
    for port in service.get("ports") or []:
        if isinstance(port, dict):
            result.append(port)
            continue
        parts = str(port).split(":")
        host_ip, published = ("", "")
        if len(parts) == 3:
            host_ip, published, target = parts
        elif len(parts) == 2:
            published, target = parts
        else:
            (target,) = parts
        result.append({"host_ip": host_ip, "published": published, "target": int(target)})
    return result


def _mounts(service, root):
    result = []
    for mount in service.get("volumes") or []:
        if isinstance(mount, dict):
            result.append(mount)
            continue
        parts = str(mount).split(":")
        source, target = parts[0], parts[1]
        read_only = len(parts) > 2 and parts[2] == "ro"
        if source.startswith("/"):
            result.append(
                {"type": "bind", "source": source, "target": target, "read_only": read_only}
            )
        elif source.startswith("."):
            resolved = os.path.normpath(str(root / source))
            result.append(
                {"type": "bind", "source": resolved, "target": target, "read_only": read_only}
            )
        else:
            result.append({"type": "volume", "source": source, "target": target})
    return result


def render(*overlays, project=PROJECT, variables=None, root=REPO, extra_files=()):
    """Static `docker compose --project-name P --env-file .env.example -f compose.ci.yaml
    [-f overlay ...] --profile test --profile migrate config --format json`."""
    if yaml is None:
        raise unittest.SkipTest("PyYAML unavailable on this interpreter")
    env_file = oss_env.parse_env_file((root / ".env.example").read_text())
    values = {**env_file, **(CI_VARS if variables is None else variables)}
    doc = yaml.safe_load((root / "compose.ci.yaml").read_text())
    for name in extra_files:
        doc = oss_env._merge(doc, yaml.safe_load((root / name).read_text()) or {})
    for overlay in overlays:
        doc = oss_env._merge(doc, yaml.safe_load(overlay) or {})
    doc = {k: v for k, v in doc.items() if not str(k).startswith("x-")}
    try:
        doc = oss_env.interpolate(doc, values)
    except oss_env.IsolationError as exc:
        raise RenderFailed(str(exc)) from None
    for service in (doc.get("services") or {}).values():
        if service.get("ports"):
            service["ports"] = _ports(service)
        if service.get("volumes"):
            service["volumes"] = _mounts(service, root)
        if isinstance(service.get("networks"), list):
            service["networks"] = {n: None for n in service["networks"]}
        if isinstance(service.get("depends_on"), list):
            service["depends_on"] = {
                n: {"condition": "service_started"} for n in service["depends_on"]
            }
        secrets = [
            s if isinstance(s, dict) else {"source": s, "target": f"/run/secrets/{s}"}
            for s in service.get("secrets") or []
        ]
        if secrets:
            service["secrets"] = secrets
    doc["name"] = project  # --project-name always wins over a file's `name:`
    return doc


class NegativeScenarios(unittest.TestCase):
    """Each scenario: render, then validate exactly as verify_ci.main does."""

    def setUp(self):
        if yaml is None:
            self.skipTest("PyYAML unavailable on this interpreter")
        # N34 harness correction: this is the candidate's own validator and repository.
        self.assertEqual(Path(verify_ci.ROOT).resolve(), REPO.resolve())
        self.assertEqual(Path(verify_ci.__file__).resolve().parent, REPO / "scripts")

    def validate(self, config, secrets_dir=None, e2e_dir=None, user=USER):
        verify_ci.validate_ci(
            config,
            secrets_dir or CI_VARS["NEXTUP_CI_SECRETS_DIR"],
            e2e_dir or CI_VARS["NEXTUP_CI_E2E_DIR"],
            user,
        )

    def fails_closed(self, produce, reason=None):
        """Render fails or the validator rejects; reason (if given) must match exactly."""
        try:
            config = produce()
        except RenderFailed:
            self.assertIsNone(reason, "expected a validator refusal, got a render failure")
            return "render-fails"
        with self.assertRaises(AssertionError) as caught:
            self.validate(config)
        if reason is not None:
            self.assertEqual(str(caught.exception), reason)
        return "validator-rejects"

    def test_P1_committed_file_is_accepted(self):
        self.validate(render())

    def test_N01_protected_project(self):
        self.fails_closed(lambda: render(project=PROTECTED_LOOKING))

    def test_N02_compose_project_name_from_environment(self):
        # Without -p, Compose would use COMPOSE_PROJECT_NAME: the validator refuses it ...
        self.fails_closed(lambda: render(project=PROTECTED_LOOKING))
        # ... and the launcher never forwards it and always passes its own random -p.
        with sandboxed_stacks({"COMPOSE_PROJECT_NAME": PROTECTED_LOOKING}) as (stacks, *_rest):
            stack = stacks[0]
            self.assertNotIn("COMPOSE_PROJECT_NAME", stack.env)
            self.assertEqual(stack.command[2:4], ["--project-name", stack.project])

    def test_N03_fixed_project(self):
        self.fails_closed(lambda: render(project="nextup-ci-test"))

    def test_N04_inherited_shell_variables_do_not_change_identity(self):
        config = render(variables={**HOSTILE, **CI_VARS})
        self.validate(config)
        text = json.dumps(config)
        self.assertEqual(sum(text.count(marker) for marker in HOSTILE_MARKERS), 0)
        self.assertEqual(json.dumps(render()), text)

    def test_N05_ci_plus_dev_overlay(self):
        dev = {
            "NEXTUP_DEV_INSTANCE_ID": "3f1c9a52-6a2e-4b7d-9c1e-2d4f6a8b0c1e",
            "NEXTUP_DEV_LOCAL_UID": "1000",
            "NEXTUP_DEV_LOCAL_GID": "1000",
        }
        self.fails_closed(
            lambda: render(variables={**CI_VARS, **dev}, extra_files=["compose.dev.yaml"])
        )

    def test_N06_ci_plus_base(self):
        self.fails_closed(lambda: render(extra_files=["compose.base.yaml"]))

    def test_N07_tripwire_plus_ci(self):
        self.assertEqual(
            self.fails_closed(lambda: render(extra_files=["compose.yaml"])), "render-fails"
        )

    def test_N08_compose_file_from_environment(self):
        with sandboxed_stacks({"COMPOSE_FILE": "compose.dev.yaml"}) as (stacks, *_rest):
            stack = stacks[0]
            self.assertNotIn("COMPOSE_FILE", stack.env)
            self.assertEqual(stack.command[-2:], ["-f", str(verify_ci.ROOT / "compose.ci.yaml")])
        self.fails_closed(lambda: render(extra_files=["compose.dev.yaml"]))

    def env(service, **values):
        return {"services": {service: {"environment": values}}}

    OVERLAYS = {
        "N09 legacy DATABASE_URL": env(
            "api", DATABASE_URL="postgresql+psycopg://u:p@postgres:5432/nextup_ci"
        ),
        "N10 inline runtime password": env("worker", NEXTUP_DB_PASSWORD="inline" * 5),
        "N11 owner secret in api": {"services": {"api": {"secrets": ["db_owner_password"]}}},
        "N12 migration key in worker": {"services": {"worker": {"secrets": ["migration_key"]}}},
        "N13 admin secret in scheduler": {
            "services": {"scheduler": {"secrets": ["db_admin_password"]}}
        },
        "N14 app secret in frontend": {"services": {"frontend": {"secrets": ["db_app_password"]}}},
        "N15 runtime as owner or migrator": env(
            "api", NEXTUP_DB_USER="nextup_ci_owner", NEXTUP_DB_ROLE="migrator"
        ),
        "N16 named persistent volume": {
            "services": {"redis": {"volumes": ["extra:/extra"]}},
            "volumes": {"extra": {}},
        },
        "N17 host bind mount": {"services": {"worker": {"volumes": ["/srv:/srv"]}}},
        "N18 external network": {
            "services": {"worker": {"networks": ["backend", "ext"]}},
            "networks": {"ext": {"external": True, "name": "shared-net"}},
        },
        "N19 tests service given egress": {
            "services": {"tests": {"networks": ["backend", "edge"]}}
        },
        "N20 backend network not internal": {"networks": {"backend": {"internal": False}}},
        "N21 postgres host port": {"services": {"postgres": {"ports": ["127.0.0.1:0:5432"]}}},
        "N22 redis host port": {"services": {"redis": {"ports": ["127.0.0.1:0:6379"]}}},
        "N23 invalid CI database name": env("api", NEXTUP_DB_NAME="otherapp"),
        "N24 foreign cluster_name": {
            "services": {"postgres": {"command": ["postgres", "-c", "cluster_name=main"]}}
        },
        "N25 renamed bootstrap superuser": env("postgres", POSTGRES_USER="nextup_ci"),
        "N26 startup waits for migrate": {
            "services": {
                "api": {"depends_on": {"migrate": {"condition": "service_completed_successfully"}}}
            }
        },
        "N27 migrate applies by default": {
            "services": {"migrate": {"command": ["apply", "--token", "x"]}}
        },
        "N27b migrate plans and applies by default": {
            "services": {"migrate": {"command": ["plan-apply"]}}
        },
        "N28 direct Alembic entrypoint": {
            "services": {"worker": {"entrypoint": ["alembic"], "command": ["upgrade", "head"]}}
        },
        "N29 integration enabled": env("worker", NEXTUP_GMAIL_SYNC_ENABLED="true"),
        "N30 n8n variable": env("worker", N8N_WEBHOOK="x"),
        "N31 live fetch without fixture mode": env(
            "worker", NEXTUP_FIXTURE_DATA_MODE="false", NEXTUP_LIVE_JOB_FETCH_ENABLED="true"
        ),
        "N31b fixture mode off": env("worker", NEXTUP_FIXTURE_DATA_MODE="false"),
        "N31c retired fixture flag": env("worker", NEXTUP_FIXTURE_FETCH_ENABLED="true"),
        "N31d provider credential": env(
            "worker", NEXTUP_ADZUNA_APP_KEY_FILE="/run/secrets/adzuna_app_key"
        ),
    }
    del env

    def test_N09_to_N31_overlays(self):
        for case, overlay in self.OVERLAYS.items():
            with self.subTest(case):
                outcome = self.fails_closed(lambda overlay=overlay: render(json.dumps(overlay)))
                self.assertEqual(outcome, "validator-rejects")

    def test_N32_secrets_directory_variable_unset(self):
        variables = {k: v for k, v in CI_VARS.items() if k != "NEXTUP_CI_SECRETS_DIR"}
        self.assertEqual(self.fails_closed(lambda: render(variables=variables)), "render-fails")
        variables = {k: v for k, v in CI_VARS.items() if k != "NEXTUP_CI_E2E_DIR"}
        self.assertEqual(self.fails_closed(lambda: render(variables=variables)), "render-fails")

    def test_N33_missing_secret_files_refused_before_any_engine_operation(self):
        """The launcher preflight refuses before `docker compose config`."""
        with sandboxed_stacks() as (stacks, _base, _repo, run):
            stack = stacks[0]
            for name in verify_ci.SECRET_NAMES:
                (stack.secrets_dir / name).unlink()
            with self.assertRaises(verify_ci.CIRefused) as caught:
                stack.compose("--profile", "test", "--profile", "migrate", "config")
            run.assert_not_called()
            self.assertIn(
                "missing: " + ", ".join(sorted(verify_ci.SECRET_NAMES)), str(caught.exception)
            )
        # Removed before the launcher starts: Stack() itself refuses -> refusal exit code.
        with sandboxed_stacks() as (_stacks, _base, _repo, run), patch("sys.stderr"):
            real_write = verify_ci.write_synthetic_secrets

            def write_then_lose(directory, audit=None):
                identities = real_write(directory, audit)
                (Path(directory) / "db_app_password").unlink()
                return identities

            with patch.object(verify_ci, "write_synthetic_secrets", write_then_lose):
                self.assertEqual(
                    verify_ci.main({"NEXTUP_INTEGRATION_APPROVED": "1"}), verify_ci.REFUSAL_EXIT
                )
            run.assert_not_called()
        # Removed mid-run: main() fails, finish() skips every engine operation, records the
        # cleanup failure and still removes the run directory; no subprocess at any point.
        with sandboxed_stacks() as (stacks, _base, _repo, run), patch("sys.stderr"):
            stack = stacks[0]
            for name in verify_ci.SECRET_NAMES:
                (stack.secrets_dir / name).unlink()
            with patch.object(verify_ci, "Stack", return_value=stack), patch("sys.stdout"):
                self.assertEqual(verify_ci.main({"NEXTUP_INTEGRATION_APPROVED": "1"}), 1)
            run.assert_not_called()
            summary = json.loads((stack.artifacts / "summary.json").read_text())
            self.assertFalse(summary["cleanup_passed"] or summary["passed"])
            self.assertFalse(stack.run_dir.exists())

    def test_N34_secrets_directory_inside_the_repository(self):
        """Harness correction: the candidate validator, its ROOT, and only the repository rule."""
        inside = str(REPO / "secrets")
        variables = {**CI_VARS, "NEXTUP_CI_SECRETS_DIR": inside}
        config = render(variables=variables)
        for secrets_dir in (inside, None):  # the probe's own directory, or this run's
            with self.assertRaises(AssertionError) as caught:
                verify_ci.validate_ci(
                    copy.deepcopy(config), secrets_dir, CI_VARS["NEXTUP_CI_E2E_DIR"], USER
                )
            self.assertEqual(str(caught.exception), "CI secrets must live outside the repository")
        # The same path cannot become a launcher run directory either.
        with self.assertRaises(verify_ci.CIRefused) as refused:
            verify_ci.check_boundaries(inside, "CI secrets directory")
        self.assertIn("overlaps the repository", str(refused.exception))
        # Control: an identical render outside the repository is accepted, so the refusal
        # above is the repository rule and nothing else.
        self.validate(render())

    def test_N35_ci_uid_zero(self):
        """Rejected by the user rule; the launcher also refuses effective UID 0."""
        for uid, gid in (("0", "0"), ("0", "1001"), ("1001", "0")):
            with self.subTest(uid=uid, gid=gid):
                variables = {**CI_VARS, "NEXTUP_CI_UID": uid, "NEXTUP_CI_GID": gid}
                with self.assertRaises(AssertionError):
                    verify_ci.validate_ci(
                        render(variables=variables),
                        CI_VARS["NEXTUP_CI_SECRETS_DIR"],
                        CI_VARS["NEXTUP_CI_E2E_DIR"],
                        None,
                    )
        with (
            redirected() as (base, repo, run),
            patch.object(verify_ci.os, "geteuid", return_value=0),
            patch("sys.stderr"),
        ):
            self.assertEqual(
                verify_ci.main({"NEXTUP_INTEGRATION_APPROVED": "1"}), verify_ci.REFUSAL_EXIT
            )
            run.assert_not_called()
            self.assertEqual(list(base.iterdir()) + list(repo.iterdir()), [])  # nothing created

    def test_N36_e2e_bind_source_outside_this_run(self):
        """Only this run's e2e directory may be mounted."""
        sources = (
            "/",
            "/srv",
            str(REPO),
            str(REPO / "test-results"),
            str(REPO / f"{PROJECT}-run/e2e"),  # run-shaped, but inside the repository
            f"{RUN}/../e2e",
            "e2e",
        )
        for source in sources:
            with self.subTest(source=source):
                variables = {**CI_VARS, "NEXTUP_CI_E2E_DIR": source}
                self.fails_closed(lambda variables=variables: render(variables=variables))
                with self.assertRaises(AssertionError):
                    self.validate(render(variables=variables), e2e_dir=source)
                with self.assertRaises(AssertionError):
                    verify_ci.validate_ci(render(variables=variables))


class RealRunRender(unittest.TestCase):
    """A real (sandboxed) launcher run directory rendered statically: accepted, no secret
    values in the render, and no collision with the private protected-resource list (if the
    harness provides one through NEXTUP_PROTECTED_RESOURCES_FILE)."""

    def test_render_of_a_real_run_directory(self):
        if yaml is None:
            self.skipTest("PyYAML unavailable on this interpreter")
        protected = oss_env.load_protected(os.environ.get(oss_env.PROTECTED_FILE_VARIABLE))
        repository = os.path.realpath(REPO)
        if any(
            verify_ci._inside(repository, p) or verify_ci._inside(p, repository)
            for p in protected["paths"]
        ):
            # Owner decision 1: when the private list protects this tree (the candidate), a
            # real run from it is refused before anything is written; runs use the copy.
            with self.assertRaises(verify_ci.CIRefused) as caught:
                verify_ci.check_root(protected["paths"])  # ROOT is the real repository here
            self.assertIn("launcher root overlaps a protected path", str(caught.exception))
        with sandboxed_stacks() as (stacks, _base, copy_root, run):
            # The redirected ROOT stands in for the verified execution copy of the candidate.
            for rel in (
                ".env.example",
                "compose.ci.yaml",
                "backend/docker/initdb/10-nextup-roles.sh",
            ):
                (copy_root / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(REPO / rel, copy_root / rel)
            stack = stacks[0]
            variables = {k: stack.env[k] for k in CI_VARS}
            config = render(project=stack.project, variables=variables, root=copy_root)
            text = json.dumps(config)
            values = [(stack.secrets_dir / n).read_text().strip() for n in verify_ci.SECRET_NAMES]
            self.assertEqual(sum(text.count(v) for v in values), 0)
            # Validated exactly as the launcher does, against its own (copy) root.
            verify_ci.validate_ci(config, stack.secrets_dir, stack.e2e_dir, stack.expected_user)
            init = config["services"]["postgres"]["volumes"][0]["source"]
            self.assertTrue(verify_ci._inside(init, os.path.realpath(copy_root)))
            run.assert_not_called()
        services = config["services"]
        envs = [s.get("environment") or {} for s in services.values()]
        found = {
            "projects": int(config["name"] in protected["projects"]),
            "volumes": len(set(config.get("volumes") or {}) & protected["volumes"]),
            "networks": sum(
                n.get("name", f"{config['name']}_{k}") in protected["networks"]
                for k, n in (config.get("networks") or {}).items()
            ),
            "databases": sum(
                e.get(k) in protected["databases"]
                for e in envs
                for k in ("POSTGRES_DB", "NEXTUP_DB_NAME")
                if k in e
            ),
            "db_users": sum(
                e.get(k) in protected["db_users"]
                for e in envs
                for k in ("POSTGRES_USER", "NEXTUP_DB_USER")
                if k in e
            ),
            "ports": sum(
                str(p.get("published")) in {str(x) for x in protected["ports"]}
                for s in services.values()
                for p in s.get("ports") or []
            ),
            "paths": sum(
                any(verify_ci._inside(m.get("source", ""), p) for p in protected["paths"])
                for s in services.values()
                for m in s.get("volumes") or []
            ),
        }
        self.assertEqual(sum(found.values()), 0, {k: v for k, v in found.items() if v})


if __name__ == "__main__":
    unittest.main()
