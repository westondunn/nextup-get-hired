# cover Content and Evidence API contracts with integration tests

> Draft only. Do not publish without explicit maintainer approval.

## User problem and intended outcome

Core résumé evidence and content-planning records need regression evidence before a public preview.
Outcome: their API contracts, state changes, relationships, and preservation behavior are covered
by synthetic integration tests.

## Current state

`backend/app/content.py` and `backend/app/evidence.py` expose substantial CRUD and workflow
behavior, but the backend suite has no dedicated Content or Evidence integration modules; résumé
file/version tests cover only part of Evidence. Reviewed at commit `f9024aa` (`main`) on
2026-11-23.

## Scope

Test create/read/update/delete, upsert or advance behavior, campaign-task links, validation,
not-found/conflict responses, ordering, and preservation. Add production fixes only when a new
test demonstrates an actual contract defect.

## Non-goals

No redesigned UI, new content workflow, coverage percentage target, or destructive fixture data.

## Capabilities and data flows

Core application data only. Synthetic records stay in the disposable test database.

## Dependencies and unresolved decisions

Use the current API as the baseline. Escalate ambiguous behavior into a separate product decision
instead of encoding it accidentally in tests.

## Acceptance criteria

- Every route and documented state transition has success and refusal coverage.
- Relationships survive unrelated updates and deletes follow the documented ownership rules.
- Tests prove user content is not overwritten by retries or adjacent operations.
- Any discovered fix is narrowly tied to a failing regression case.

## Security, privacy, failure handling and data preservation

Use synthetic text and files only. Do not weaken file limits, URL sanitization, or database guards.

## Evidence expected

Dedicated integration test modules passing in the approved disposable-stack verification.

## Documentation affected

Update development validation notes only if the new evidence changes a documented claim.

## Contributor notes

- Suggested branch: `test/content-evidence-contracts` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: content/evidence tests and narrowly proven fixes.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: proposed core public preview tracker.
- Actual branch and pull request: not created yet.
- Verification evidence: pending.
