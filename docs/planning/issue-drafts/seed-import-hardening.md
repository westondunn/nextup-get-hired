# make seed preview and apply one bounded, truthful operation

> Draft only. Do not publish without explicit maintainer approval.

## User problem and intended outcome

A user reviewing a seed import must be able to trust that the preview describes what Apply will
do and that a failed or repeated import cannot silently lose their edits. Outcome: preview and
apply use one validated plan with atomic, idempotent, data-preserving behavior.

## Current state

`backend/app/seed_import.py` accepts unbounded dictionaries. Preview proposes tasks from
`lead_reconciliation`, while apply reads and discards that section. Planning and mutation are
separate implementations, and the unused `SeedPayload` still uses deprecated Pydantic config.
Reviewed at commit `f9024aa` (`main`) on 2026-11-23.

## Scope

Define a strict bounded input schema, build one side-effect-free plan used by preview and apply,
make every reported count and action truthful, preserve terminal tasks and user edits, and apply
the plan in one transaction. Cover retries, duplicates, invalid references, and rollback.

## Non-goals

No new onboarding design, remote seed source, arbitrary schema compatibility, or automatic reset
of existing campaign data.

## Capabilities and data flows

Core application data only. The JSON flows from the local browser to the local API and database;
nothing leaves NextUp.

## Dependencies and unresolved decisions

Coordinate the eventual first-run path so it does not require seed JSON. Decide in the issue
whether `lead_reconciliation` is implemented or rejected; preview and apply must agree either way.

## Acceptance criteria

- Preview and apply consume the same validated plan and report identical intended actions.
- Size, count, type, date, identifier, and reference limits fail with fixed safe errors.
- Reapplying a payload creates no duplicates and does not reopen terminal tasks or replace edits.
- Any failed write rolls back the entire import, and a retry produces the original plan.
- The unused deprecated model is removed or replaced by the active schema.

## Security, privacy, failure handling and data preservation

Treat every string and relationship as untrusted. Do not log payload content. Preserve existing
records and edits on validation or database failure. Any schema change uses a new `oss_NNNN`
revision and never edits pinned history or `LINEAGE.sha256`.

## Evidence expected

Unit tests for planning and validation plus guarded integration tests for atomicity, idempotency,
rollback, and preservation, all with synthetic payloads.

## Documentation affected

Document the accepted seed format and clarify its relationship to guided first run.

## Contributor notes

- Suggested branch: `bugfix/seed-import-plan` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: seed import, campaign data, integration tests.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: proposed core public preview tracker.
- Actual branch and pull request: not created yet.
- Verification evidence: pending.
