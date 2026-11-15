# Contributing to NextUp

**Outside contributions are not being accepted yet.** NextUp is pre-release and is being prepared for public development. This guide is preparatory. It records how the maintainer works today, so that the process is written down before contributions open. It is not an invitation to start work.

This file is the one place the contribution policy is stated. The [README](README.md#development-and-contributions) repeats it in a line and links here.

## What this means today

- Pull requests from outside the project are not being accepted.
- No issue is offered for outside work. The `help wanted` and `good first issue` labels are not in use, and every outcome in the [roadmap](docs/ROADMAP.md) states its availability.
- There is no commitment to respond to issues or pull requests opened from outside the project.
- Security reports are handled separately, as described next.

## Reporting a security problem

Do not describe a vulnerability in a public issue, pull request or discussion. Follow the private process in [SECURITY.md](SECURITY.md).

Never post real credentials, tokens or personal data anywhere in this repository, including issues and pull requests.

## How work is tracked

- Each planned outcome is one GitHub issue. Issues are grouped as sub-issues of a parent issue, currently [#3](https://github.com/westondunn/nextup-get-hired/issues/3), and an issue that waits on another records that as a blocked-by link.
- The [roadmap](docs/ROADMAP.md) lists the outcomes and the evidence for each completed one. The [release checklist](docs/RELEASE_CHECKLIST.md) lists the gates that must be met before anything is described as publicly supported.
- An outcome is ticked only when its evidence is linked. A merged pull request or a closed issue is not evidence on its own.
- Decisions that shape more than one issue are recorded under [docs/decisions/](docs/decisions/).
- The repository does not use a GitHub Project.
- New issues start from the implementation issue template. Each issue names a suggested branch. The branch actually used is recorded under the issue's Links once it exists, and the two can differ.

## Branches and pull requests

The [branching guide](docs/BRANCHING.md) is the single source for branch names, the pull-request workflow and the merge gates. None of it is repeated here.

What the guide does not cover:

- The pull-request template asks for the commands actually run and, separately, for the checks that were not run, with reasons. Report both as they happened. A check that was skipped is listed as skipped.
- Reference an issue as "Part of #N" unless merging the pull request should close it. The reason is in the guide under [Review, verify, and merge](docs/BRANCHING.md#review-verify-and-merge).
- The hosted workflow runs the full verification for every pull request and every push to `main`, as a check named `verify`. A branch with no pull request gets no hosted run. The `main` ruleset does not require it to pass, so read its result before a merge.

## Setting up

The requirements and the local development stack are described in the [development notes](docs/DEVELOPMENT.md). That page is not an installation guide, and no platform is supported yet.

The fast checks below also need two tools on the host:

- [uv](https://docs.astral.sh/uv/), which runs the backend checks on Python 3.12 or later.
- Node.js with npm, for the frontend: version 20.19 or later in the 20 series, or 22.12 or later.

Never run plain `docker compose` in this directory. `compose.yaml` is a tripwire that fails on purpose; the stack is started through `scripts/local.py`, as the development notes describe.

## Checks

### Fast checks on the host

These start no containers. Each line is run from the repository root.

```sh
# Backend unit tests, lint and format
cd backend && uv run --locked pytest -q
cd backend && uv run --locked ruff check . && uv run --locked ruff format --check .

# Tooling tests
python3 -m unittest discover -s scripts/tests -v

# Frontend
cd frontend && npm ci
cd frontend && npm test
cd frontend && npm run typecheck && npm run format:check
cd frontend && npm run build
```

What they leave out:

- The backend integration suites skip themselves here, and the browser tests are not run at all. Both run only in the full verification.
- Without PyYAML, the tooling tests that parse the Compose files are skipped. A local run can then pass where the hosted workflow, which has PyYAML, fails.

### Full verification

```sh
NEXTUP_INTEGRATION_APPROVED=1 scripts/verify.sh
```

This builds a disposable stack, runs every suite and removes the stack. The variable is a deliberate opt-in for one run. What the run does and refuses to do is in the development notes under [Full verification](docs/DEVELOPMENT.md#full-verification). The hosted workflow runs the same script.

## Rules for every change

The merge gates are in [section 5 of the branching guide](docs/BRANCHING.md#5-nextup-specific-merge-gates). The ones that come up most often:

- **Synthetic data only.** No real personal data, account or credential goes into code, fixtures, tests, logs, issues or pull requests.
- **Pinned migrations.** The files under `backend/migrations/versions/` are never edited or reformatted. See [Database migrations](docs/DEVELOPMENT.md#database-migrations).
- **Loopback only.** The API has no authentication, so no change publishes a port on a network.
- **Integrations stay off.** Every external integration is switched off in every shipped configuration, and a change does not enable one by default.
- **No values in messages.** Error messages and log lines do not contain configuration values or secrets.
- **Claims follow evidence.** Nothing is described as supported, tested or secure without linked evidence. The vocabulary is in [INTEGRATIONS.md](docs/INTEGRATIONS.md).

## Not covered yet

This guide does not yet say how contributions will work once they open. The following are undecided:

- the terms under which a contribution is licensed (the project itself is under the [MIT License](LICENSE.md));
- what review and response a contributor can expect;
- a code of conduct;
- which issues will be available, and how they will be marked.
