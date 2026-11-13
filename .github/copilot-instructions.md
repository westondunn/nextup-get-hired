# Copilot instructions for NextUp

NextUp is a pre-release, self-hosted, single-user job-search organiser. Keep this file
consistent with the root `AGENTS.md`, `CLAUDE.md`, and `docs/DEVELOPMENT.md`; consult those
for fuller operational details.

## Build, test, and lint

Run these examples from the repository root:

```sh
# Backend unit tests
(cd backend && uv run --locked pytest -q)
(cd backend && uv run --locked pytest tests/test_scoring.py::test_full_match_is_100_with_components_and_evidence -q)

# Backend lint and formatting
(cd backend && uv run --locked ruff check .)
(cd backend && uv run --locked ruff format --check .)

# Scripts' standard-library tests
python3 -m unittest discover -s scripts/tests -v
python3 -m unittest discover -s scripts/tests -p test_local.py -v

# Frontend (install dependencies first with npm ci in frontend/)
(cd frontend && npm test)
(cd frontend && npx vitest run src/hub/csv.test.ts)
(cd frontend && npx vitest run src/hub/csv.test.ts -t "returns nothing for empty text")
(cd frontend && npm run typecheck)
(cd frontend && npm run format:check)
(cd frontend && npm run build)
```

Backend integration tests, migration round trips, and browser tests run through
`scripts/verify.sh` against a disposable Docker stack. It performs migrations and is
deliberately gated: run `NEXTUP_INTEGRATION_APPROVED=1 scripts/verify.sh` only with explicit
per-run user opt-in. Do not run plain `docker compose`; use `python3 scripts/local.py --env dev`
for local stack operations. `start` does not migrate; `migrate` displays a plan and requires
confirmation.

## Architecture and data flow

- The backend is FastAPI with feature routers in flat modules under `backend/app/`; `main.py`
  registers the routers. SQLAlchemy models are centralized in `models.py`.
- Celery tasks are in `*_tasks.py` modules and must be listed in `celery_app.py`'s `include`.
  Work that must survive broker outages persists an intent before publishing; the scheduled
  recovery task re-dispatches eligible intents.
- Database identity and schema changes are guarded in `backend/app/guard/`. API, worker, and
  scheduler startup checks are read-only. Schema changes must go through the guard's
  transaction path; do not bypass it with direct Alembic commands. Existing migration files
  are SHA-256-pinned in `backend/migrations/LINEAGE.sha256`; never edit or reformat them.
- `load_settings()` / `get_settings()` in `config.py` is the process configuration path. It
  accepts the `NEXTUP_*` namespace, loads file-backed secrets, validates deployment identity,
  and refuses legacy or unknown configuration. Keep secrets out of logs, errors, and reprs.
- Provider adapters in `backend/app/sources/` normalize provider data to shared shapes.
  External integrations are disabled in shipped configurations; provider entry points must
  use `require_live_requests()` before network access. CI/test fixture mode uses bundled
  synthetic fixtures and must not make live requests.
- The frontend has no router: `NextupHub.tsx` owns the current `Page` state and renders
  feature views from `hub/`. Feature API modules use `/api/...`; shared fetch/error handling
  is in `jobs-api.ts`, and Vite proxies `/api` to the local API.

## Repository-specific constraints

- The API has no authentication. Preserve loopback-only port publishing; never expose it to
  a network.
- Keep tests synthetic. `backend/tests/conftest.py` isolates developer configuration and
  installs a synthetic test identity. Integration tests require the disposable verification
  stack and are not ordinary host-side unit tests.
- Render stored URLs through `frontend/src/hub/safe.ts`'s `safeHref` (HTTP/HTTPS only).
- Python formatting/lint rules are configured in `backend/pyproject.toml` (100 columns;
  Ruff `E`, `F`, `I`, `UP`, `B`). Frontend formatting uses Prettier configured in `frontend/`.
