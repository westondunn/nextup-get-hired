# Prove offline core workflows and persistence through the visible UI

> Draft only. Review and approve before creating a GitHub issue.

## User problem and intended outcome

Current browser tests often seed state through APIs and do not prove that a new user can complete the core workflow with integrations absent. Outcome: deterministic browser evidence covers all six core workflows, reload/restart persistence, and unexpected egress refusal.

## Current state

The individual views have unit and browser coverage, but no suite exercises the full `CORE_ONBOARDING.md` matrix through visible actions from an empty profile. Reviewed at commit `f9024aa` (`main`) on 2026-11-23.

## Scope

- Exercise application/stage/history, task completion, contact update, résumé reopen, manual job discovery, and optional profile.
- Verify reload and service restart persistence.
- Run with integrations/AI absent and record unexpected outbound attempts.

## Non-goals

- No live provider, clean-machine installation, or representative-user session.
- No test-only product bypass.

## Capabilities and data flows

Core local workflows with synthetic data. External egress is denied after dependencies are available.

## Dependencies and unresolved decisions

Blocked by the in-app first-run path and application accessibility baseline. Full disposable
verification requires explicit per-run opt-in.

## Acceptance criteria

- Every workflow is completed through accessible UI controls.
- Saved state survives reload and restart.
- Any unexpected external request fails the run and is reported without payload content.

## Security, privacy, failure handling and data preservation

Use only disposable-stack synthetic records. Preserve evidence without secrets or personal data; cleanup remains scoped to the run.

## Evidence expected

Playwright results, egress record, persistence assertions, and a hosted verification link.

## Documentation affected

Release checklist, core onboarding evidence, and development validation table.

## Contributor notes

- Suggested branch: `test/core-workflow-browser-evidence` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: `frontend/tests/`, CI test helpers, evidence docs.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: core public preview tracker, once created
- Blocked by: in-app first run and the application accessibility baseline
- Actual branch and pull request: not created yet
- Verification evidence: pending
