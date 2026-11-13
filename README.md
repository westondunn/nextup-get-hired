# NextUp

NextUp is a self-hosted application for organising a job search. It runs on your own machine and keeps your data in your own database.

> **Status: pre-release, under active development.** NextUp is not ready for production use. Installation instructions, first-run onboarding and public release validation are still in progress, and no platform is supported yet. [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) describes the existing tooling and what has been tested.

## What it is for

NextUp brings the working parts of a job search into one place:

- a daily view of what needs attention, and a task plan with a calendar;
- applications, with their stages, timeline and offer details;
- a job board, saved searches and alerts, with relevance scoring against your profile;
- contacts and correspondence;
- résumé versions and supporting evidence;
- basic metrics.

It is designed for one person running their own instance. It is not a hosted service and has no multi-user features.

## Current status

| Area | State |
|---|---|
| Core application (backend, worker, frontend) | Implemented; under test |
| Database migration safeguards | Implemented; runtime validation in progress |
| Portable installation (Linux, macOS, Windows) | In progress; no platform is supported yet. Verification has been run on Linux with Docker only |
| First-run onboarding | Planned |
| External integrations (job-board feeds, read-only mail and calendar sync) | Present in the code; switched off in every shipped configuration; no supported way to enable them yet |
| Authentication | None. The API is unauthenticated, and the development configuration publishes ports on the loopback interface only. Do not expose it to a network |
| Documentation | Being rewritten. Current documents: this README, [development notes](docs/DEVELOPMENT.md), the [optional external classifier interface](docs/CORRESPONDENCE_SYNC.md), the [roadmap](docs/ROADMAP.md), the [release checklist](docs/RELEASE_CHECKLIST.md) and the [security policy](SECURITY.md) |
| Release validation | In progress |

Expect breaking changes, including to configuration and data formats, before a first release.

## Architecture

- **Backend:** Python, FastAPI, SQLAlchemy and Alembic.
- **Background work:** Celery worker and scheduler, with Redis as the broker.
- **Database:** PostgreSQL.
- **Frontend:** React and TypeScript, built with Vite.
- **Packaging:** container images orchestrated with Docker Compose.

The application uses separate database roles for administration, schema changes and normal operation. Schema migrations go through a guard that checks which database it is connected to before it changes anything. These safeguards are still being validated and should not be relied on yet.

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | API, background tasks, database models, migrations and tests |
| `frontend/` | Web interface and its tests |
| `scripts/` | Development and verification tooling |
| `env/` | Environment templates (no secrets) |
| `docs/` | Development notes and interface descriptions |
| `compose*.yaml` | Service definitions for development, staging and CI |

## Development and contributions

The project is being prepared for public development. Until that work is complete:

- there are no supported setup instructions, and the tooling described in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) may change without notice;
- outside contributions are not being accepted yet;
- contribution guidelines will be published before the first release;
- security reports are handled as described in [SECURITY.md](SECURITY.md).

## Licence

NextUp is released under the MIT License. See [LICENSE.md](LICENSE.md).

Third-party dependencies are not included in this repository and remain under their own licences.
