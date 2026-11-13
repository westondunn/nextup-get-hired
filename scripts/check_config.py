"""Validate Compose isolation and editor configuration without starting anything.

`docker compose config` renders each OSS environment from its committed template plus
throwaway, non-secret identity values (instance ID, UID/GID, a placeholder staging
secrets directory), then scripts/oss_env.py checks identity, roles, secrets, volumes,
images, ports, database targets and the migration guard. It never reads `.env.*` or any
secret file, and secrets appear in the render as file paths only.
"""

import argparse
import json
import os
import subprocess
import uuid
from pathlib import Path

import oss_env

ROOT = Path(__file__).resolve().parents[1]
# Never created or read: the render only needs an absolute path outside the repository.
PLACEHOLDER_SECRETS_DIR = "/nonexistent/nextup-oss-stg-validation-secrets"


def validation_variables(env) -> dict[str, str]:
    values = {f"{env.prefix}INSTANCE_ID": str(uuid.uuid4())}
    if env.name == "dev":
        values[f"{env.prefix}LOCAL_UID"] = "1000"
        values[f"{env.prefix}LOCAL_GID"] = "1000"
    else:
        values[f"{env.prefix}SECRETS_DIR"] = PLACEHOLDER_SECRETS_DIR
        values[f"{env.prefix}SECRETS_GID"] = "1000"
    return values


def render(env, extra=()):
    files = env.files + tuple(extra)
    command = ["docker", "compose", "--project-name", env.project, "--env-file", env.example]
    for filename in files:
        command.extend(["-f", filename])
    command.extend(["--profile", "migrate", "--profile", "test", "config", "--format", "json"])
    variables = oss_env.child_environment(os.environ)
    variables.update(validation_variables(env))
    result = subprocess.run(
        command, cwd=ROOT, env=variables, check=True, capture_output=True, text=True
    )
    return json.loads(result.stdout)


def validate_environments(render_fn=render, protected=None):
    checked = []
    for env, extra in (
        (oss_env.ENVIRONMENTS["dev"], ()),
        (oss_env.ENVIRONMENTS["dev"], ("compose.debug.yaml",)),
        (oss_env.ENVIRONMENTS["staging"], ()),
    ):
        oss_env.validate_config(render_fn(env, extra), env, protected)
        label = " + ".join(env.files + tuple(extra))
        print(f"PASS: isolation: {label}")
        checked.append(label)
    return checked


def check_services(services):
    """The disposable CI stack's contract (compose.ci.yaml); dev/staging use oss_env."""
    for name, service in services.items():
        for port in service.get("ports", []):
            assert port["host_ip"] == "127.0.0.1", f"Nonlocal port on {name}: {port}"
    for name in ("postgres", "redis"):
        assert not services[name].get("ports"), f"Host port published for {name}"
    schedulers = [
        name for name, service in services.items() if "beat" in (service.get("command") or [])
    ]
    assert schedulers == ["scheduler"], f"Expected exactly one scheduler, got {schedulers}"
    # Startup never migrates; migrations run only through the guard's plan/apply.
    for name, service in services.items():
        for dependency in service.get("depends_on") or {}:
            assert dependency not in ("migrate", "tests"), f"{name} waits for {dependency}"


def check_editor_files():
    for path in sorted((ROOT / ".vscode").glob("*.json")):
        json.loads(path.read_text())
        print(f"PASS: valid JSON: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--example-env",
        action="store_true",
        help="Accepted for compatibility; templates are always used and .env.* never read",
    )
    parser.parse_args()
    validate_environments()
    check_editor_files()
