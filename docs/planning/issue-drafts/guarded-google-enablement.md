# Add a guarded, off-by-default Google enablement path

> Draft only. Review and approve before creating a GitHub issue.

## User problem and intended outcome

The Google connection code cannot be exercised through a shipped local configuration because configuration validation requires both sync flags to remain false. Outcome: provide one explicit, documented, off-by-default enablement path suitable for controlled validation without weakening isolation.

## Current state

Google consent and stored credentials are implemented with mocked tests, but `scripts/oss_env.py` and shipped configuration refuse enabled sync flags. Settings therefore reports that no account can be connected. Reviewed at commit `f9024aa` (`main`) on 2026-11-23.

## Scope

- Decide and implement the narrow development/validation opt-in.
- Preserve default-off behavior, loopback publication, local session, file-backed key, and capability separation.
- Add configuration, refusal, and rendered-Compose tests.

## Non-goals

- No default enablement, staging support, live-account test, or support-status change.
- No new Google capability or scope.

## Capabilities and data flows

Optional Gmail correspondence read and Google Calendar read. When explicitly enabled and used, OAuth and API requests go to Google as documented.

## Dependencies and unresolved decisions

Blocked by #10 evidence reconciliation and #11 lifecycle design. #14 remains separately approval-gated.

## Acceptance criteria

- Existing shipped defaults remain false and make no provider request.
- The opt-in is explicit, validated, local-only, and cannot be inherited accidentally from ambient variables.
- Each capability can be enabled independently and only requested when enabled.

## Security, privacy, failure handling and data preservation

Keep secrets file-backed and value-free in logs/errors. Refusal happens before external requests. Disabling preserves imported records and user edits.

## Evidence expected

Configuration and launcher tests, mocked connection coverage, secret audit, and full disposable verification only with per-run approval.

## Documentation affected

Development/setup notes, Google ADR implementation status, integrations matrix, and release checklist.

## Contributor notes

- Suggested branch: `feature/guarded-google-enablement` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: configuration, launcher validation, environment templates, tests.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: #3
- Blocked by: #10 and #11
- Actual branch and pull request: not created yet
- Verification evidence: pending
