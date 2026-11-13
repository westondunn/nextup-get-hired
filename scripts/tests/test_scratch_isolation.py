"""The script suite must be safe to run with the CI launcher's own
environment, in particular with NEXTUP_CI_SCRATCH_ROOT already set.

The real launcher runs ``python -m unittest discover -s scripts/tests`` as its runner-tests
step while NEXTUP_CI_SCRATCH_ROOT points at the approved scratch root. Neither collecting
nor running the suite may create, change or remove anything there. This module proves it
with a synthetic scratch root: it runs test collection and then the whole suite in child
interpreters whose environment mirrors the launcher's non-secret variables, and checks
that the synthetic root is untouched.

No engine, network or real scratch root is involved: every path is created here and
removed afterwards.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRATCH_VARIABLE = "NEXTUP_CI_SCRATCH_ROOT"
PROTECTED_VARIABLE = "NEXTUP_PROTECTED_RESOURCES_FILE"
APPROVAL_VARIABLE = "NEXTUP_INTEGRATION_APPROVED"
# Set in the child interpreters so the nested suite does not start another nested suite.
NESTED_MARKER = "CI_SCRIPT_SUITE_NESTED"
TIMEOUT_SECONDS = 600


def _snapshot(directory):
    """Identity and content listing of a directory; any creation or removal changes it."""
    info = os.lstat(directory)
    names = sorted(str(p.relative_to(directory)) for p in Path(directory).rglob("*"))
    return (info.st_dev, info.st_ino, info.st_mode, info.st_mtime_ns, tuple(names))


@unittest.skipIf(os.environ.get(NESTED_MARKER) == "1", "already inside the nested suite")
class ConfiguredScratchRoot(unittest.TestCase):
    """The launcher's environment must not turn unit tests into real scratch-root writers."""

    def setUp(self):
        self.base = Path(os.path.realpath(tempfile.mkdtemp(prefix="ci-suite-regression-")))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.scratch = self.base / "configured-scratch-root"
        self.scratch.mkdir(mode=0o700)
        self.scratch.chmod(0o700)
        # A synthetic protected list, as the real run supplies one; it names only a path
        # created here, so it cannot refuse the repository or the temporary directories.
        self.protected = self.base / "protected.json"
        self.protected.write_text(json.dumps({"paths": [str(self.base / "protected-area")]}))
        self.environ = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("NEXTUP_", "COMPOSE_"))
        }
        self.environ.update(
            {
                SCRATCH_VARIABLE: str(self.scratch),
                PROTECTED_VARIABLE: str(self.protected),
                APPROVAL_VARIABLE: "1",
                NESTED_MARKER: "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )

    def child(self, *arguments):
        return subprocess.run(  # noqa: S603 - fixed interpreter and arguments
            [sys.executable, "-B", *arguments],
            cwd=REPO,
            env=self.environ,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )

    def test_collection_creates_nothing_in_the_configured_scratch_root(self):
        before = _snapshot(self.scratch)
        result = self.child(
            "-c",
            "import sys, unittest\n"
            "suite = unittest.defaultTestLoader.discover('scripts/tests')\n"
            "errors = unittest.defaultTestLoader.errors\n"
            "sys.exit(0 if suite.countTestCases() > 0 and not errors else 1)\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertEqual(_snapshot(self.scratch), before)

    def test_full_suite_passes_and_leaves_the_configured_scratch_root_untouched(self):
        before = _snapshot(self.scratch)
        result = self.child("-m", "unittest", "discover", "-s", "scripts/tests")
        tail = result.stderr[-3000:]
        self.assertEqual(result.returncode, 0, tail)
        self.assertRegex(tail, r"Ran \d+ tests")
        self.assertNotIn("FAILED", tail)
        self.assertEqual(_snapshot(self.scratch), before)  # no run directory, no removal
        self.assertEqual(list(self.scratch.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
