# Development notes

NextUp is pre-release. This page describes the tooling that exists in the repository and states what has and has not been validated. It is not an installation guide, and no platform is supported yet.

## What has been validated

| Item | State |
|---|---|
| Full verification in a disposable stack (`scripts/verify_ci.py`) | Run on Linux (x86-64) with Docker Engine and the Compose plugin |
| The same on macOS or Windows | Not tested |
| The hosted workflow in `.github/workflows/ci.yml` | Runs the same verification on a hosted `ubuntu-24.04` runner for every pull request and every push to `main`. Passing on `main` on 2026-11-13, for example [this run](https://github.com/westondunn/nextup-get-hired/actions/runs/43538353763) at commit `7370e9a`. Current results are on the [Actions page](https://github.com/westondunn/nextup-get-hired/actions/workflows/ci.yml?query=branch%3Amain) |
| The local development launcher (`scripts/local.py`) | Covered by unit tests; not yet validated on a clean machine |
| Display of dates in the Search Plan view outside UTC | Unit-tested in UTC and America/Chicago across the 2027-03-14 and 2026-11-01 clock changes (`frontend/src/hub/SearchPlanView.dst.test.tsx`), in [this hosted run](https://github.com/westondunn/nextup-get-hired/actions/runs/43672928458) at commit `c143b87`. An all-day calendar event is shown by its date, with no time ([#38](https://github.com/westondunn/nextup-get-hired/issues/38)). No zone east of UTC is tested, and there is no browser test |
| Calendar import across daylight-saving changes | Unit-tested with synthetic events (`backend/tests/test_calendar_dst.py`), in [this hosted run](https://github.com/westondunn/nextup-get-hired/actions/runs/43658531564) at commit `be66581`. An event time without an offset is read in the zone the event names ([#39](https://github.com/westondunn/nextup-get-hired/issues/39)). No live calendar has been used, so it is not known whether the provider sends that form |

## Requirements

- Docker Engine with the Compose plugin.
- Python 3.12 or later on the host, for the scripts. They use the standard library only.
- Optional: PyYAML, for the tooling tests that parse the Compose files. Without it those tests are skipped, so a local run can pass where the hosted workflow, which has it, fails.

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
- `start` also generates `.secrets/dev/setup_code`, the code that starts a local session (`POST /api/session`). An installation created before this file existed gets it on its next `start`. Changing or running mail and calendar sync requires that session; enter the code under Settings, Integrations. So do the routes that save and report a Google client, and the route that starts a Google connection. The address Google sends the browser back to (`GET /api/google/callback`) cannot require one; it completes only a connection that a session started. No other route requires one. See [decisions/0001-local-session-boundary.md](decisions/0001-local-session-boundary.md).
- `start` also generates `.secrets/dev/token_key`, the key that encrypts the credentials of a stored Google connection. Only the `api` and `worker` services receive it. No connection can be made in a development stack yet. The routes exist: one saves the client ID and secret of a Google client (`PUT /api/google/client`), one sends the browser to Google's consent screen (`POST /api/google/connect`), and one receives the answer and stores the grant (`GET /api/google/callback`). All of them refuse while both sync settings are off, and the launcher does not yet accept them switched on. Settings, Integrations has a card for them: it saves the client, shows the redirect address to register, starts the connection and shows the outcome. In a development stack the card only reports why no account can be connected. All of it has been tested with simulated Google responses only. Sync uses a stored connection when one exists, and otherwise the three Google secrets in configuration if all are present. Losing or replacing the file will make a stored connection unreadable, and the remedy is to connect again. Staging has no such key. See [decisions/0003-google-connection.md](decisions/0003-google-connection.md).
- `start` never migrates. Until `migrate` has initialised the schema, the services refuse to work. The same applies after an update that adds a migration revision: the services refuse with `NXG-L03` until `migrate` has been run again. `migrate` shows a read-only plan first and applies it only after you type the confirmation code it prints.
- The API and the web interface are published on the loopback interface only, by default on ports 18000 and 15173.
- Open them as `127.0.0.1` or `localhost`. The API answers `400` to any other host name, and `403` to a state-changing request that a browser reports as coming from another origin. A proxy in front of the API must forward the browser's `Host` header unchanged, as `frontend/vite.config.ts` does. See [decisions/0001-local-session-boundary.md](decisions/0001-local-session-boundary.md).
- There is no command that removes data volumes.

**The API has no authentication. Do not publish these ports on a network.**

## External integrations

Job-board feeds, read-only mail and calendar sync, and the optional external classifier are switched off in every shipped configuration, and there is no supported way to enable them yet. The classifier's interface is described in [CORRESPONDENCE_SYNC.md](CORRESPONDENCE_SYNC.md). What exists in the code and what has been tested are recorded separately in [INTEGRATIONS.md](INTEGRATIONS.md).

## Branches and pull requests

Work happens on short-lived topic branches that are merged into `main` through pull requests. The naming rules, pull-request expectations and merge gates are in the [branching guide](BRANCHING.md). The guide is the maintainer's adopted workflow. Branch names are not checked automatically, and outside contributions are not being accepted yet; the policy is in [CONTRIBUTING.md](../CONTRIBUTING.md).

- The hosted workflow's check is named `verify`. It is not a required check: the `main` ruleset requires a pull request and linear history, but no passing check.
- The verification runs once for each commit pushed to a pull request, and once for each push to `main`. A branch with no pull request gets no hosted run: open a draft pull request, or start the workflow by hand from the Actions page.
- A closing keyword next to an issue number in a pull-request description closes that issue on merge, even when the sentence is negated. Linking an issue in the pull request's sidebar does the same.

## Database migrations

- The files under `backend/migrations/versions/` are pinned by SHA-256 in `backend/migrations/LINEAGE.sha256`. The migration guard refuses to run if a single byte differs, so never edit or reformat an existing revision, including its comments and line endings.
- Migrations run only through the guard, which checks which database it is connected to before it changes anything.
- Revisions added after the pinned history are named `oss_NNNN` and extend the same chain. The first is `oss_0030`. They are not added to the pin file.
