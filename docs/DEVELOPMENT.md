# Development notes

NextUp is pre-release. This page describes the tooling that exists in the repository and states what has and has not been validated. It is not an installation guide, and no platform is supported yet.

## What has been validated

| Item | State |
|---|---|
| Full verification in a disposable stack (`scripts/verify_ci.py`) | Run on Linux (x86-64) with Docker Engine and the Compose plugin |
| The same on macOS or Windows | Not tested |
| The hosted workflow in `.github/workflows/ci.yml` | Not yet run on a hosted runner |
| The local development launcher (`scripts/local.py`) | Covered by unit tests; not yet validated on a clean machine |
| Display of dates in the Search Plan view outside UTC | Not tested |

## Requirements

- Docker Engine with the Compose plugin.
- Python 3.12 or later on the host, for the scripts. They use the standard library only.

Everything else (Python and Node dependencies, PostgreSQL, Redis, browsers for the end-to-end tests) runs in containers.

## Full verification

```sh
NEXTUP_INTEGRATION_APPROVED=1 scripts/verify.sh
```

This builds the images and starts a disposable stack under a random project name of the form `nextup-ci-<12 hex>`. It then runs the linters, the migration round trips, the backend, frontend and browser tests, and removes the stack. It uses synthetic fixture data only, and no external integration is enabled.

- The variable is a deliberate opt-in for one run. Without it the script refuses and starts nothing.
- The run never targets a development or staging stack and never removes volumes.
- The run keeps its working files in a scratch directory outside the repository: `nextup-ci-<uid>` under the system temporary directory, or the directory named by `NEXTUP_CI_SCRATCH_ROOT`.
- It refuses to run as root.
- Building the images downloads base images and dependencies, so the first run needs network access.

## Local development stack

```sh
python3 scripts/local.py --env dev doctor    # check tools and configuration; starts nothing
python3 scripts/local.py --env dev start     # build and start
python3 scripts/local.py --env dev migrate   # show the migration plan; apply after confirmation
python3 scripts/local.py --env dev status
python3 scripts/local.py --env dev stop      # stop; data is kept
```

- `start` creates `.env.dev` from `env/dev.env.example` and generates database passwords as files under `.secrets/dev/`. Neither is committed.
- `start` also generates `.secrets/dev/setup_code`, the code that starts a local session (`POST /api/session`). An installation created before this file existed gets it on its next `start`. Changing or running mail and calendar sync requires that session; enter the code under Settings, Integrations. No other route requires one. See [decisions/0001-local-session-boundary.md](decisions/0001-local-session-boundary.md).
- `start` never migrates. Until `migrate` has initialised the schema, the services refuse to work. `migrate` shows a read-only plan first and applies it only after you type the confirmation code it prints.
- The API and the web interface are published on the loopback interface only, by default on ports 18000 and 15173.
- Open them as `127.0.0.1` or `localhost`. The API answers `400` to any other host name, and `403` to a state-changing request that a browser reports as coming from another origin. A proxy in front of the API must forward the browser's `Host` header unchanged, as `frontend/vite.config.ts` does. See [decisions/0001-local-session-boundary.md](decisions/0001-local-session-boundary.md).
- There is no command that removes data volumes.

**The API has no authentication. Do not publish these ports on a network.**

## External integrations

Job-board feeds, read-only mail and calendar sync, and the optional external classifier are switched off in every shipped configuration, and there is no supported way to enable them yet. The classifier's interface is described in [CORRESPONDENCE_SYNC.md](CORRESPONDENCE_SYNC.md). What exists in the code and what has been tested are recorded separately in [INTEGRATIONS.md](INTEGRATIONS.md).

## Database migrations

- The files under `backend/migrations/versions/` are pinned by SHA-256 in `backend/migrations/LINEAGE.sha256`. The migration guard refuses to run if a single byte differs, so never edit or reformat an existing revision, including its comments and line endings.
- Migrations run only through the guard, which checks which database it is connected to before it changes anything.
