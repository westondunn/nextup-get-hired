# Validate core setup from a clean machine

> Draft only. Review and approve before creating a GitHub issue.

## User problem and intended outcome

A passing developer or CI run does not show that the documented setup works from the claimed platform's actual starting state. Outcome: record a reproducible clean-machine run for every platform configuration claimed for the core preview.

## Current state

No clean-machine validation is recorded; developer and CI verification exercise different paths.
Reviewed at commit `f9024aa` (`main`) on 2026-11-23.

## Scope

- Start from a pristine VM/machine matching the accepted platform ADR.
- Exercise prerequisites, setup, failure/retry cases, all core workflows, stop/restart, and data retention.
- Record the exact commit, versions, architecture, and redacted evidence.

## Non-goals

- No live provider, personal data, unsupported platform, or support claim beyond the run.

## Capabilities and data flows

Core installation and local workflows. Dependency downloads are recorded; unexpected runtime egress fails validation.

## Dependencies and unresolved decisions

Blocked by guided setup, in-app first run, core E2E evidence, and the accepted platform decision.

## Acceptance criteria

- The documented path succeeds from the stated pristine starting state.
- Missing prerequisite, port conflict, cancellation, and interrupted startup recovery preserve data.
- Claims are limited to the exact platform/configuration exercised.

## Security, privacy, failure handling and data preservation

Use synthetic data and a disposable or dedicated test machine. Do not record secrets, absolute personal paths, or machine identifiers.

## Evidence expected

Dated validation record, redacted artifacts, and the matching hosted verification result.

## Documentation affected

Setup guide, README status, development notes, integrations status where relevant, and release checklist.

## Contributor notes

- Suggested branch: `docs/core-clean-machine-validation` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: validation records and public status docs.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: core public preview tracker, once created
- Actual branch and pull request: not created yet
- Verification evidence: pending
