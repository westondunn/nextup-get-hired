# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

NextUp is a self-hosted, single-user job-search organiser: FastAPI + SQLAlchemy + Alembic backend, Celery worker and beat scheduler (Redis broker), PostgreSQL, and a React/TypeScript/Vite frontend, all run with Docker Compose. It is pre-release. The API has no authentication, so ports are published on loopback only; never change that.

## Commands

### Fast checks on the host (no containers)

```sh
# Backend unit tests (integration tests skip themselves without RUN_INTEGRATION=1)
cd backend && uv run --locked pytest -q
cd backend && uv run --locked pytest tests/test_scoring.py::test_full_match_is_100_with_components_and_evidence -q   # single test
cd backend && uv run --locked ruff check . && uv run --locked ruff format --check .

# Tooling tests for scripts/ (standard library only, unittest)
python3 -m unittest discover -s scripts/tests -v
python3 -m unittest discover -s scripts/tests -p test_local.py -v   # single module

# Frontend (after npm ci in frontend/)
cd frontend && npm test                      # vitest, src/**/*.test.{ts,tsx}
cd frontend && npx vitest run src/hub/csv.test.ts   # single file
cd frontend && npm run typecheck && npm run format:check
cd frontend && npm run build                 # tsc --noEmit && vite build
```

CI also lints `scripts/` with ruff using `backend/pyproject.toml` as the config (line length 100, rules E, F, I, UP, B).

### Full verification (disposable Docker stack)

```sh
NEXTUP_INTEGRATION_APPROVED=1 scripts/verify.sh
```

This is the only way to run the `*_integration.py` backend suites, migration round trips, Playwright browser tests (`frontend/tests/*.spec.ts`) and the outage/recovery exercises. It builds images, starts a random `nextup-ci-<12 hex>` project, and removes it afterwards. It refuses without the opt-in variable, refuses as root, and refuses if any `COMPOSE_*` selection variable is set. The variable is a per-run opt-in by the user: do not set it on your own initiative. The same script (`scripts/verify_ci.py`) is what `.github/workflows/ci.yml` runs.

### Local development stack

```sh
python3 scripts/local.py --env dev doctor    # checks only; starts nothing
python3 scripts/local.py --env dev start     # build and start; creates .env.dev and .secrets/dev/
python3 scripts/local.py --env dev migrate   # shows plan; applies after a typed confirmation code
python3 scripts/local.py --env dev debug     # start with debugpy on 127.0.0.1:15678 (api) / 15679 (worker)
python3 scripts/local.py --env dev status
python3 scripts/local.py --env dev stop      # data is kept; there is no volume-removal command
```

API on `127.0.0.1:18000`, frontend on `127.0.0.1:15173`. For a host-side Vite server against the dev stack API: `cd frontend && API_PROXY_TARGET=http://127.0.0.1:18000 npm run dev -- --host 127.0.0.1 --port 15174`.

**Never run plain `docker compose ...` in this directory.** `compose.yaml` is a deliberate tripwire that fails; real definitions are `compose.base.yaml` plus `compose.dev.yaml` / `compose.staging.yaml`, always selected with an explicit project name by `scripts/local.py`. `compose.ci.yaml` is used only by `verify_ci.py`. Compose override files are refused. `start` never migrates, and services refuse to work until `migrate` has initialised the schema. Staging migrations are an operator procedure and are refused by the launcher.

## Architecture

### Database guard (`backend/app/guard/`)

The central safety mechanism; most surprising behaviour in this repo traces back to it.

- Three database roles per environment: admin, owner/migrator, and runtime (`<prefix>_app`). Role names, database name and Postgres `cluster_name` are fixed per environment (`ENV_PREFIX`, `EXPECTED_CLUSTER` in `app/config.py`).
- Every service process passes a read-only identity check before doing anything: the image entrypoint is `python -m app.guard exec --`, the FastAPI lifespan and Celery `worker_init`/`beat_init` call it, and `app/db.py` installs it as the engine's `first_connect` hook.
- `guard.apply_in_transaction` is the **only** path that may change the schema (advisory lock, facts, policy decision, single-use token, Alembic, privilege lock-down, post-check in one transaction). The CLI (`python -m app.guard plan|plan-apply|apply`), `migrate_programmatically` (tests/CI) and Alembic's `env.py` all funnel into it. Bare `alembic upgrade` cannot write; without an authorization Alembic runs in a READ ONLY transaction. There is no test-only or environment-variable bypass, and tokens are accepted on stdin only.
- `backend/migrations/LINEAGE.sha256` pins every file in `migrations/versions/` by SHA-256. The guard refuses if a single byte differs, so **never edit or reformat an existing revision** (comments and line endings included), and do not add entries to the pin file (it must hold exactly revisions 0001-0029). New revisions must have a revision id of the form `oss_NNNN` and extend the single linear chain from the current head; anything else is refused (`guard/lineage.py`, `NXG-L04`).
- Guard refusals carry fixed `NXG-*` codes and value-free messages (`guard/errors.py`).

### Configuration and secrets (`backend/app/config.py`, `secrets_files.py`)

- `load_settings(environ)` / `get_settings()` is the only way a process gets real configuration. It reads `NEXTUP_*` names only, loads `*_FILE` secrets, and **refuses** (rather than ignores) legacy names such as `DATABASE_URL`, `POSTGRES_*`, `PG*`, and unprefixed Google/Adzuna variables.
- `Settings(...)` can be constructed directly in tests, but then has no database identity.
- No setting value may appear in an error, log line or `repr`; launcher scripts likewise never echo command output except fixed guard refusal lines. Keep new error messages value-free.
- Every external integration (Adzuna, Greenhouse, employer boards, Gmail, Google Calendar, external email classifier) is off in every shipped configuration. `sources.require_live_requests(settings)` is the chokepoint each provider entry point must call first; in fixture data mode job sources are served from the bundled `*.fixture.json` files and everything else refuses.

### Backend layout (`backend/app/`)

- `request_boundary.py` is ASGI middleware on every request: a fixed host allowlist (`localhost`, `127.0.0.1`; `api` and `frontend` only in `ci`/`test`) and refusal of cross-origin `POST`/`PUT`/`PATCH`/`DELETE` (`Sec-Fetch-Site`, `Origin` vs `Host`). The list is a constant, not a setting. It relies on the Vite proxy keeping `changeOrigin: false`; `tests/conftest.py` adds `testserver` for the test client only. See `docs/decisions/0001-local-session-boundary.md`.
- `local_session.py` implements the local session (layer 3 of the same decision record): `POST /api/session` exchanges the setup code (`NEXTUP_SETUP_CODE_FILE`, mounted into the `api` service only, file-only) for an `HttpOnly` cookie; sessions live in Redis under a hash of the identifier. `require_session` is the route dependency, applied to `PUT /api/correspondence` and `POST /api/correspondence/sync` only (a test pins that set); tests about other behaviour opt out with the `local_session` fixture in `tests/conftest.py`. The Settings prompt is `frontend/src/hub/LocalSessionCard.tsx`. The request body is parsed by hand because FastAPI's validation errors echo the input.
- Flat modules, one per feature. Each feature module defines its own `APIRouter` (and usually its Pydantic schemas) and is registered in `main.py`; all ORM models live in `models.py`.
- Celery tasks live in `*_tasks.py` modules, which must be listed in `include=[...]` in `celery_app.py`; periodic work is in `beat_schedule` there.
- `recovery.py` implements durable task intents: rows (`DiagnosticRun`, `JobFetch`) are written before publishing to the broker, and a scheduled task re-dispatches or fails pending ones, so a broker outage leaves recoverable state rather than lost work.
- `sources/` holds provider adapters that normalise to common shapes (`sources/common.py`); `scoring.py` and `relevance.py` rank jobs against the profile.
- `docs/CORRESPONDENCE_SYNC.md` is the contract for the optional external classifier, which writes only to `email_classifications`; NextUp's own detection stays authoritative.

### Backend tests (`backend/tests/`)

- `conftest.py` strips legacy, libpq and Google variables from the environment and supplies a synthetic test identity, so unit tests run anywhere.
- `*_integration.py` files are skipped unless `RUN_INTEGRATION=1` and only work inside the CI `tests` service (`NEXTUP_ENV=test`, migrator identity). `integration_db.py` creates disposable `nextup_test_<32 hex>` schemas / `nextup_migration_test_<32 hex>` databases, migrates them through the real guard, and hands code under test runtime-role engines.
- `test_integration.py` is different: it runs inside the running `api` container against the live CI stack with the runtime credential.
- All test data is synthetic (`tests/fixtures/profile.synthetic.json`); never add real personal data or credentials.

### Frontend (`frontend/src/`)

- No router: `NextupHub.tsx` is the shell and switches between views in `hub/*View.tsx` with a `Page` state value.
- API access is through per-feature `*-api.ts` modules using plain `fetch` against `/api/...` (Vite proxies `/api` to `API_PROXY_TARGET`). The shared `request` helper is in `jobs-api.ts`.
- Render stored URLs through `safeHref` in `hub/safe.ts` (http/https only).
- Tailwind CSS v4 via the Vite plugin; Prettier for formatting; unit tests are colocated `*.test.ts(x)`, Playwright specs are in `frontend/tests/`.

### Tooling (`scripts/`)

Standard library only (Python 3.12+), so it runs on a bare host. `oss_env.py` defines the environments and validates the rendered Compose configuration (identity, roles, secrets, volumes, images, ports) before anything starts; `local.py` is the launcher; `verify_ci.py` orchestrates the disposable CI run, including `secret_audit.py`, which fails the run if any synthetic secret or migration token appears in logs, artifacts or container metadata.
