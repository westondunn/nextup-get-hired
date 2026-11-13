#!/usr/bin/env bash
# Full verification. It never targets a development, staging or any other existing
# stack: the only path is scripts/verify_ci.py, which creates a random, disposable
# nextup-ci-<12 hex> project on tmpfs and never removes volumes.
# Real containers, migrations and integration tests need an explicit opt-in, given
# by setting NEXTUP_INTEGRATION_APPROVED=1 for that one run.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ "${NEXTUP_INTEGRATION_APPROVED:-}" != "1" ]; then
  echo "Refused: verification starts a disposable Docker stack and runs migrations and" >&2
  echo "integration tests. Set NEXTUP_INTEGRATION_APPROVED=1 to confirm this one run." >&2
  exit 3
fi
for variable in COMPOSE_PROJECT_NAME COMPOSE_FILE COMPOSE_PATH_SEPARATOR COMPOSE_PROFILES COMPOSE_ENV_FILES; do
  if [ -n "${!variable:-}" ]; then
    echo "Refused: unset ${variable}; verification selects its own disposable project." >&2
    exit 3
  fi
done

exec python3 scripts/verify_ci.py
