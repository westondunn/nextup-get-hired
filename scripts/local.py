"""Start and inspect one explicitly selected Nextup OSS Compose environment.

    python3 scripts/local.py --env dev {doctor,start,debug,status,stop,migrate}
    python3 scripts/local.py --env staging --confirm-project nextup-oss-stg {doctor,status,stop}

Every Compose call names its project, env file and files explicitly. The rendered
configuration is validated (scripts/oss_env.py) before anything starts. There is no
`down` or volume removal. `start` never migrates: `migrate` (dev only) shows the guard's
read-only plan and applies it only after you type its confirmation code. Staging
migrations are an operator procedure on the host shell, never this script.
"""

import argparse
import json
import os
import platform
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import guard_session
import oss_env

ROOT = Path(__file__).resolve().parents[1]
ACTIONS = ("doctor", "start", "debug", "status", "stop", "migrate")
STAGING_MIGRATION_REFUSAL = (
    "Refused: staging migrations are run by an operator on the host shell as a "
    "separate, deliberate step, never by this launcher. Nothing was run."
)
MIGRATION_REFUSED_EXIT = 3
OVERRIDE_FILES = (
    "compose.override.yaml",
    "compose.override.yml",
    "docker-compose.override.yaml",
    "docker-compose.override.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
)
GUARD_PREFIX = "nextup-guard: "


class LocalStack:
    def __init__(self, env_name, root=ROOT, environ=None, debug=False):
        environ = os.environ if environ is None else environ
        self.env = oss_env.get_environment(env_name)
        if debug and self.env.name != "dev":
            raise oss_env.IsolationError("The debug overlay is available only for dev")
        oss_env.check_process_environment(environ)
        self.root = Path(root)
        self.protected = oss_env.load_protected(environ.get(oss_env.PROTECTED_FILE_VARIABLE))
        self.process_env = oss_env.child_environment(environ)
        self.env_file = self.root / self.env.env_file
        files = self.env.files + (("compose.debug.yaml",) if debug else ())
        self.command = [
            "docker",
            "compose",
            "--project-name",
            self.env.project,
            "--env-file",
            str(self.env_file),
        ]
        for filename in files:
            self.command.extend(["-f", str(self.root / filename)])

    def run(self, command, timeout=60, input_text=None):
        try:
            return subprocess.run(
                command,
                cwd=self.root,
                env=self.process_env,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                input=input_text,
            ).stdout.strip()
        except FileNotFoundError:
            raise RuntimeError(f"Missing executable: {command[0]}; install it manually") from None
        except subprocess.CalledProcessError as exc:
            # Never echo command output in general. The guard's own refusal lines are
            # fixed texts without values, so those (and only those) are shown.
            guard = [
                line for line in (exc.stderr or "").splitlines() if line.startswith(GUARD_PREFIX)
            ][:3]
            detail = ("; " + " | ".join(guard)) if guard else ""
            raise RuntimeError(f"Command failed: {' '.join(command[:2])} ...{detail}") from None

    def compose(self, *args, timeout=60, input_text=None):
        return self.run(self.command + list(args), timeout=timeout, input_text=input_text)

    # ---------- checks ----------

    def check_layout(self):
        for filename in (
            "scripts/oss_env.py",
            "compose.base.yaml",
            self.env.overlay,
            f"{oss_env.INIT_SCRIPT_DIR}/10-nextup-roles.sh",
        ):
            path = self.root / filename
            if path.is_symlink() or not path.is_file():
                raise RuntimeError(f"Expected Nextup OSS workspace file: {filename}")
        present = [name for name in OVERRIDE_FILES if (self.root / name).exists()]
        if present:
            raise oss_env.IsolationError(
                "Refusing: unsupported Compose override files are present: " + ", ".join(present)
            )

    def check_tools(self):
        print(f"Workspace: {self.root}")
        print(f"Environment: {self.env.name} (project {self.env.project})")
        print(f"Kernel: {platform.release()}")
        print(
            "Docker client/server: "
            + self.run(
                ["docker", "version", "--format", "{{.Client.Version}} / {{.Server.Version}}"]
            )
        )
        print(self.run(["docker", "compose", "version"]))

    def check_config(self):
        oss_env.check_env_file(self.env_file, self.env)
        if self.env.name == "dev":
            oss_env.check_dev_secret_files(self.root)
        rendered = self.compose(
            "--profile", "migrate", "--profile", "test", "config", "--format", "json"
        )
        config = json.loads(rendered)
        oss_env.validate_config(config, self.env, self.protected)
        print(
            f"PASS: {self.env.project} isolation (identity, roles, secrets, volumes, images, "
            "ports, database, migrations)"
        )

    def doctor(self):
        self.check_layout()
        self.check_tools()
        self.check_config()

    # ---------- dev provisioning (never staging) ----------

    def ensure_env_file(self):
        if self.env_file.exists() or self.env_file.is_symlink():
            print(f"Keeping existing {self.env.env_file} unchanged.")
            return
        if self.env.name != "dev":
            raise RuntimeError(
                f"{self.env.env_file} is missing; create it from {self.env.example} "
                "(it is never generated for staging)."
            )
        fills = {
            f"{self.env.prefix}INSTANCE_ID": str(uuid.uuid4()),
            f"{self.env.prefix}LOCAL_UID": str(os.getuid()),
            f"{self.env.prefix}LOCAL_GID": str(os.getgid()),
        }
        lines = []
        for line in (self.root / self.env.example).read_text().splitlines():
            key = line.split("=", 1)[0]
            lines.append(f"{key}={fills.pop(key)}" if key in fills and "=" in line else line)
        if fills:
            raise RuntimeError(f"{self.env.example} lacks: " + ", ".join(sorted(fills)))
        descriptor = os.open(self.env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            output.write("\n".join(lines) + "\n")
        print(f"Created {self.env.env_file} with a new instance ID (mode 0600).")

    def ensure_secrets(self):
        """Generate any missing dev secret file; never overwrite or print one."""
        if self.env.name != "dev":
            raise RuntimeError("Secrets are generated for dev only")
        base = self.root / ".secrets"
        directory = self.root / oss_env.DEV_SECRETS_DIR
        for path in (base, directory):
            if not path.exists() and not path.is_symlink():
                path.mkdir(mode=0o700)
        created = []
        for name in oss_env.SECRET_NAMES:
            path = directory / name
            if path.exists() or path.is_symlink():
                continue
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "w") as output:
                output.write(secrets.token_urlsafe(32) + "\n")
            created.append(name)
        oss_env.check_dev_secret_files(self.root)
        if created:
            print(
                f"Generated {len(created)} new local secret file(s) in "
                f"{oss_env.DEV_SECRETS_DIR}/ (mode 0600)."
            )

    # ---------- actions ----------

    def start(self):
        self.check_layout()
        self.check_tools()
        self.ensure_env_file()  # refuses for staging: never generated
        if self.env.name == "dev":
            self.ensure_secrets()
        self.check_config()
        print(
            f"Building and starting {self.env.project}; first startup may take minutes.", flush=True
        )
        print(
            "Note: start never migrates. Services refuse until `migrate` has initialized "
            "the schema."
        )
        self.compose("up", "--build", "--wait", "--wait-timeout", "180", timeout=900)
        self.status()

    def migrate(self, prompt=input, interactive=None):
        """Dev only: ``guard plan-apply`` shows the plan and a one-time code; the operator types
        the code and only then does the guard apply, in its own process. The authorization
        token never leaves the guard: no argument, variable, pipe or log carries it."""
        if self.env.name != "dev":
            raise oss_env.IsolationError(STAGING_MIGRATION_REFUSAL)
        interactive = sys.stdin.isatty() if interactive is None else interactive
        if not interactive:
            raise RuntimeError("migrate needs an interactive terminal to confirm the plan")
        self.doctor()
        self.compose("up", "--wait", "--wait-timeout", "120", "postgres", timeout=300)
        command = self.command + [
            "--profile",
            "migrate",
            "run",
            "--rm",
            "-T",
            "migrate",
            "plan-apply",
        ]

        def decide(lines, code):
            for line in lines:
                if line.startswith(GUARD_PREFIX) and line != guard_session.AWAITING:
                    print(line)
            typed = prompt(
                f"Type the confirmation code {code} to apply this plan (anything else cancels): "
            ).strip()
            return typed if typed == code else None

        try:
            session = guard_session.plan_apply(
                command, decide=decide, cwd=self.root, env=self.process_env, timeout=1800
            )
        except FileNotFoundError:
            raise RuntimeError(f"Missing executable: {command[0]}; install it manually") from None
        shown = session.guard_lines()
        if not session.awaited:  # nothing to apply, or refused before any confirmation
            for line in shown:
                print(line)
            if session.returncode == 0:
                print("Nothing to apply.")
                return
            raise RuntimeError("Command failed: docker compose ...; " + " | ".join(shown[-3:]))
        if not session.confirmed:
            print("Cancelled; nothing was applied.")
            return
        after = (
            shown[shown.index(guard_session.AWAITING) + 1 :]
            if guard_session.AWAITING in shown
            else []
        )
        for line in after:
            print(line)
        if session.returncode:
            raise RuntimeError("Command failed: docker compose ...; " + " | ".join(after[-3:]))

    def status(self):
        print(self.compose("ps"))
        address = self.compose("port", "api", "8000")
        if not address.startswith("127.0.0.1:"):
            raise RuntimeError("API is not running on an expected localhost port.")
        try:
            with urllib.request.urlopen(f"http://{address}/api/health", timeout=15) as response:
                health = json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"API health returned HTTP {exc.code}; inspect System status."
            ) from None
        print("Dependencies: " + json.dumps(health["checks"], sort_keys=True))
        print("Scheduler: " + health["scheduler"])
        if health["status"] != "ok":
            raise RuntimeError("Application dependencies are not healthy.")
        frontend = self.compose("port", "frontend", "5173")
        if not frontend.startswith("127.0.0.1:"):
            raise RuntimeError("Frontend is not running on an expected localhost port.")
        print(f"Open http://{frontend}")
        print(f"API documentation: http://{address}/docs")

    def stop(self):
        self.doctor()
        print(self.compose("stop", timeout=120))
        print(f"Stopped {self.env.project}; volumes and data retained.")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--env", required=True, choices=sorted(oss_env.ENVIRONMENTS))
    parser.add_argument(
        "--confirm-project",
        help="Required for staging: type the staging project name to confirm the target.",
    )
    parser.add_argument("action", choices=ACTIONS)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        env = oss_env.get_environment(args.env)
        if env.name == "staging" and args.action == "migrate":
            print(STAGING_MIGRATION_REFUSAL, file=sys.stderr)
            return MIGRATION_REFUSED_EXIT
        if env.name == "staging" and args.confirm_project != env.project:
            raise oss_env.IsolationError(f"Staging actions require --confirm-project {env.project}")
        stack = LocalStack(args.env, debug=args.action == "debug")
        if args.action in ("start", "debug"):
            stack.start()
        elif args.action == "doctor":
            stack.doctor()
        elif args.action == "status":
            stack.doctor()
            stack.status()
        elif args.action == "stop":
            stack.stop()
        elif args.action == "migrate":
            stack.migrate()
    except (OSError, RuntimeError, AssertionError, ValueError, subprocess.SubprocessError) as exc:
        # Do not echo rendered Compose configuration or credentials on failure.
        detail = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        print(f"FAIL: {detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
