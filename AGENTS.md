# Repository Guidelines

## Project Structure & Module Organization

NextUp combines FastAPI, SQLAlchemy, Celery, PostgreSQL, Redis, and a React/TypeScript frontend.

- `backend/app/`: API modules, models, workers, provider adapters, and bundled JSON fixtures; `backend/migrations/`: guarded Alembic revisions; `backend/tests/`: pytest suites.
- `frontend/src/`: UI, colocated tests, and `styles.css`; `frontend/src/hub/`: feature views; `frontend/tests/`: browser tests.
- `scripts/`: development/verification tooling and `scripts/tests/`; `env/`: configuration templates; `docs/`: development notes and integration contracts.

## Build, Test, and Development Commands

Run these from the repository root:

- `python3 scripts/local.py --env dev doctor`: check prerequisites without starting services.
- `python3 scripts/local.py --env dev start`: build/start development services. Then use `python3 scripts/local.py --env dev migrate` to initialise the schema after confirmation. `stop` preserves data.
- `cd backend && uv run --locked pytest -q`: backend unit tests; integration suites skip automatically.
- `python3 -m unittest discover -s scripts/tests -v`: tooling tests.
- In `frontend/`, run `npm ci`, then `npm test` for unit tests or `npm run build` for typechecking and bundling.
- In `backend/`, run `uv run --locked ruff check .` and `uv run --locked ruff format --check .`; in `frontend/`, run `npm run format:check`.

Use the launcher rather than plain `docker compose`; see `docs/DEVELOPMENT.md`.

## Coding Style & Naming Conventions

Python uses four-space indentation, snake_case names, type annotations, and Ruff's 100-column limit. TypeScript uses two spaces, PascalCase component filenames, and kebab-case API modules. Prettier specifies single quotes, trailing commas, and 100-column width.

## Testing Guidelines

Use pytest `test_*.py`, colocated Vitest/Testing Library `*.test.ts(x)`, and Playwright `frontend/tests/*.spec.ts`. Cover changed behaviour with synthetic fixtures; no numeric coverage threshold is configured.

Full integration, migration, recovery, and browser verification uses `NEXTUP_INTEGRATION_APPROVED=1 scripts/verify.sh`. Agents must obtain explicit per-run user opt-in before setting this variable; tests use a disposable stack.

## Commit & Pull Request Guidelines

History contains only `Initial public release`; no established prefix convention exists. Use concise, descriptive subjects. Describe changes, link relevant issues, report checks, and include screenshots for UI changes. Outside contributions are currently closed; consult `README.md`.

## Security & Configuration

Keep unauthenticated services on loopback. The API also refuses non-local host names and cross-origin state-changing requests (`backend/app/request_boundary.py`), and requires a local session (`backend/app/local_session.py`, `require_session`) for changing or running correspondence sync only; neither is authentication. Integration status and support claims are recorded in `docs/INTEGRATIONS.md`; do not describe a disabled or untested integration as supported. Never commit secrets or personal data. Preserve existing migration files and `LINEAGE.sha256`; new `oss_NNNN` revisions must extend the chain and run through the guard.
