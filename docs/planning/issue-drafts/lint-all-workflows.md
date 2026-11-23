# Lint every checked-in GitHub Actions workflow

> Draft only. Review and approve before creating a GitHub issue.

## User problem and intended outcome

The verification runner lints only `ci.yml`, so a syntax or actionlint defect in another checked-in workflow can pass. Outcome: the workflow-lint step validates every workflow file deterministically.

## Current state

`scripts/verify_ci.py` invokes pinned actionlint with the single argument `ci.yml`; `.github/workflows/maintainer-approval.yml` is not included. Reviewed at commit `f9024aa` (`main`) on 2026-11-23.

## Scope

- Pass every checked-in `.yml` or `.yaml` workflow to the existing pinned actionlint image.
- Add runner tests that fail when a workflow is omitted.
- Preserve read-only mounting and the existing pinned image digest.

## Non-goals

- No workflow behavior, trigger, permission, ruleset, or approval-gate change.
- No unpinned actionlint installation.

## Capabilities and data flows

None. The check reads repository workflow files inside the disposable verification runner.

## Dependencies and unresolved decisions

None. File ordering should be deterministic for stable evidence.

## Acceptance criteria

- Both current workflows are linted.
- Adding another workflow automatically includes it or makes the contract test fail.
- Existing verification isolation and pinned dependency checks still pass.

## Security, privacy, failure handling and data preservation

The lint container receives only the read-only workflow directory. A lint failure stops verification without changing repository or application data.

## Evidence expected

Focused runner unit tests, script lint/format checks, and guarded full verification only with separate per-run approval.

## Documentation affected

`docs/DEVELOPMENT.md` only if its verification inventory names the workflow coverage.

## Contributor notes

- Suggested branch: `ci/lint-all-workflows` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: `scripts/verify_ci.py`, `scripts/tests/`.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: governance execution tracker, once created
- Actual branch and pull request: not created yet
- Verification evidence: pending
