"""Verification entry points refuse unsafe targets. Docker and Python are stubbed."""

import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_ci
import verify_failures

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/verify.sh"


class VerifyShell(unittest.TestCase):
    """Runs a copy of verify.sh with stub `python3` and `docker` that only record calls."""

    def run_script(self, **env):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts/verify.sh").write_text(SCRIPT.read_text())
            stubs = root / "stubs"
            stubs.mkdir()
            log = root / "calls.log"
            for name in ("python3", "docker"):
                stub = stubs / name
                stub.write_text(f'#!/bin/sh\necho "{name} $*" >> "{log}"\nexit 0\n')
                stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
            result = subprocess.run(
                ["/bin/bash", str(root / "scripts/verify.sh")],
                env={"PATH": f"{stubs}:/usr/bin:/bin", **env},
                capture_output=True,
                text=True,
                timeout=20,
            )
            return result, (log.read_text().splitlines() if log.exists() else [])

    def test_refuses_without_approval_and_runs_nothing(self):
        for value in (
            {},
            {"NEXTUP_INTEGRATION_APPROVED": "0"},
            {"NEXTUP_INTEGRATION_APPROVED": "yes"},
        ):
            with self.subTest(env=value):
                result, calls = self.run_script(**value)
                self.assertEqual(result.returncode, 3)
                self.assertEqual(calls, [])

    def test_refuses_inherited_project_selection_even_when_approved(self):
        for key in ("COMPOSE_PROJECT_NAME", "COMPOSE_FILE", "COMPOSE_PROFILES"):
            with self.subTest(key=key):
                result, calls = self.run_script(NEXTUP_INTEGRATION_APPROVED="1", **{key: "other"})
                self.assertEqual(result.returncode, 3)
                self.assertEqual(calls, [])

    def test_approved_run_only_delegates_to_the_disposable_runner(self):
        result, calls = self.run_script(NEXTUP_INTEGRATION_APPROVED="1")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(calls, ["python3 scripts/verify_ci.py"])

    def test_script_never_calls_docker_itself(self):
        body = [
            line
            for line in SCRIPT.read_text().splitlines()
            if not line.lstrip().startswith(("#", "echo"))
        ]
        self.assertFalse(any("docker" in line or "alembic" in line for line in body))
        subprocess.run(["/bin/bash", "-n", str(SCRIPT)], check=True)


class OutageChecks(unittest.TestCase):
    def test_refuses_without_injected_disposable_stack(self):
        compose, request = MagicMock(), MagicMock()
        for kwargs in (
            {},
            {"compose_fn": compose, "request_fn": request},
            {"compose_fn": compose, "request_fn": request, "project": "nextup-oss-dev"},
            {"compose_fn": compose, "request_fn": request, "project": "nextup-ci-test"},
            {"compose_fn": compose, "request_fn": request, "project": "other-stack"},
            {"compose_fn": None, "request_fn": request, "project": "nextup-ci-0123456789ab"},
        ):
            with (
                self.subTest(kwargs=kwargs.get("project")),
                self.assertRaises(verify_failures.UnsafeTarget),
            ):
                verify_failures.main(**kwargs)
        compose.assert_not_called()
        request.assert_not_called()

    def test_accepts_only_a_random_ci_project(self):
        compose = MagicMock()
        request = MagicMock(side_effect=RuntimeError("stop after the guard"))
        with self.assertRaisesRegex(RuntimeError, "stop after the guard"):
            verify_failures.main(
                compose_fn=compose, request_fn=request, project="nextup-ci-0123456789ab"
            )
        compose.assert_not_called()  # health is requested before any stop

    def test_module_has_no_default_compose_target(self):
        self.assertFalse(hasattr(verify_failures, "compose"))
        self.assertFalse(hasattr(verify_failures, "request"))
        self.assertNotIn("subprocess", (REPO / "scripts/verify_failures.py").read_text())

    def test_standalone_cli_refuses(self):
        result = subprocess.run(
            [sys.executable, str(REPO / "scripts/verify_failures.py")],
            env={"PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, verify_failures.REFUSAL_EXIT)


class CiRunnerApproval(unittest.TestCase):
    def test_refuses_before_creating_a_stack(self):
        with patch.object(verify_ci, "Stack") as stack, patch("sys.stderr"):
            for environ in ({}, {"NEXTUP_INTEGRATION_APPROVED": "true"}):
                self.assertEqual(verify_ci.main(environ), verify_ci.REFUSAL_EXIT)
        stack.assert_not_called()

    def test_outage_checks_receive_the_ci_project(self):
        source = (REPO / "scripts/verify_ci.py").read_text()
        self.assertIn("project=stack.project", source)

    def test_integration_flag_is_set_only_inside_the_ci_stack(self):
        """T-UNIT-03c: RUN_INTEGRATION appears only as `exec -e` into the CI project."""
        for name in (
            "scripts/verify.sh",
            "scripts/local.py",
            "scripts/check_config.py",
            "scripts/verify_failures.py",
        ):
            self.assertNotIn("RUN_INTEGRATION", (REPO / name).read_text(), name)
        lines = [
            line
            for line in (REPO / "scripts/verify_ci.py").read_text().splitlines()
            if "RUN_INTEGRATION" in line
        ]
        self.assertTrue(lines and all('"RUN_INTEGRATION=1"' in line for line in lines))


class ExplicitProjectEverywhere(unittest.TestCase):
    def test_every_compose_invocation_names_its_project(self):
        """T-STATIC-03: any script that builds a docker compose command passes a project."""
        for path in sorted((REPO / "scripts").glob("*.py")) + sorted(
            (REPO / "scripts").glob("*.sh")
        ):
            text = path.read_text()
            builds = (
                '"docker",\n            "compose"' in text
                or '["docker", "compose"' in text
                or re.search(r"^\s*docker compose\b", text, re.M)
            )
            if builds:
                with self.subTest(path=path.name):
                    self.assertIn("--project-name", text)


if __name__ == "__main__":
    unittest.main()
