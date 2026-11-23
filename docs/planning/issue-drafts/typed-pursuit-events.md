# store typed pursuit events for reliable metrics

> Draft only. Do not publish without explicit maintainer approval.

## User problem and intended outcome

Metrics should not change when user-facing timeline wording changes or contains an incidental
keyword. Outcome: generated pursuit events carry a stable kind and bounded structured payload,
and metrics use those fields instead of parsing display text.

## Current state

`backend/app/career.py` derives transitions, contacts, replies, and funnel timings through substring
searches of `PursuitEvent.message`; `backend/app/models.py` has no event kind. Reviewed at commit
`f9024aa` (`main`) on 2026-11-23.

## Scope

Define event kinds and payloads for generated lifecycle events, add them through a guarded
migration, write them at every generating path, update metrics and exports, and preserve legacy
rows as explicit unknown/manual events.

## Non-goals

No analytics service, user tracking, rewriting of historical messages, or inference of a precise
kind when legacy evidence is ambiguous.

## Capabilities and data flows

Core application metrics. Pursuit actions remain in the local database; nothing leaves NextUp.

## Dependencies and unresolved decisions

Lock the event vocabulary and which manual timeline events may choose a kind before migration
implementation. Keep the human-readable message as presentation, not authority.

## Acceptance criteria

- Generated events have a documented kind and validated payload.
- Metrics, weekly summaries, funnels, and exports read structured fields.
- Legacy rows remain visible and are counted only where their meaning is unambiguous.
- Changing message wording cannot change metric results.
- Migration upgrade/downgrade and mixed legacy/new data are tested.

## Security, privacy, failure handling and data preservation

Do not add telemetry or data egress. Preserve every legacy message, date, attachment, and link.
Use a new `oss_NNNN` revision; never alter pinned revisions or `LINEAGE.sha256`.

## Evidence expected

Migration round trips and synthetic integration tests for every event kind, legacy rows, exports,
and unchanged metric denominators.

## Documentation affected

Document the event vocabulary and metric provenance.

## Contributor notes

- Suggested branch: `refactor/typed-pursuit-events` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: career API, models, migrations, metrics tests.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: proposed core public preview tracker.
- Actual branch and pull request: not created yet.
- Verification evidence: pending.
