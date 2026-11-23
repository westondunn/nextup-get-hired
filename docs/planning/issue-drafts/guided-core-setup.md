# Implement guided setup for the local core application

> Draft only. Review and approve before creating a GitHub issue.

## User problem and intended outcome

New users must understand terminals, Compose, guarded migrations, and several recovery states. Outcome: implement the accepted guided setup for the selected initial platform while preserving all existing safety boundaries.

## Current state

The developer launcher can doctor, start, migrate, report status, and stop, but it is not a guided end-user path and has not been clean-machine validated. Reviewed at commit `f9024aa` (`main`) on 2026-11-23.

## Scope

- Implement prerequisite checks, local preparation, migration review/confirmation, progress, retry, open, and stop behavior from `CORE_ONBOARDING.md`.
- Reuse guarded launcher primitives and preserve an installation identity across retries.
- Keep every integration and AI feature off.

## Non-goals

- No provider setup, automatic reset, remote exposure, or support for platforms outside the accepted ADR.
- No bypass of the migration guard.

## Capabilities and data flows

Core installation. Dependency registries may receive ordinary package/image requests; job-search data remains local.

## Dependencies and unresolved decisions

Blocked by #28 acceptance and the initial platform/packaging ADR.

## Acceptance criteria

- Each failure gives one actionable recovery path and retry preserves existing state.
- Cancellation and interrupted startup do not remove data or secrets.
- The final address is verified as loopback before it is opened.

## Security, privacy, failure handling and data preservation

Never log secret contents or confirmation input. Preserve volumes, files, and database state. Refuse uncertain identity or migration state.

## Evidence expected

Unit tests for failure/retry paths, focused integration coverage, accessibility checks for any UI, and later clean-machine evidence.

## Documentation affected

Setup guide, development notes, roadmap, and release checklist.

## Contributor notes

- Suggested branch: `feature/guided-core-setup` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: launcher/setup surface selected by the accepted ADR.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: core public preview tracker, once created
- Blocked by: #28 and the platform ADR
- Actual branch and pull request: not created yet
- Verification evidence: pending
