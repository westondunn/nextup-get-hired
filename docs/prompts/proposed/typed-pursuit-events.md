---
work_id: proposed-typed-pursuit-events
status: proposed
issue: pending
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.2-sol
depends_on: proposed-core-public-preview-tracker
approval_gates: issue-publication,full-verification,migration
canonical_sources: docs/planning/issue-drafts/typed-pursuit-events.md,backend/app/career.py,backend/app/models.py
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Replace metric text parsing with typed pursuit events

## Outcome

Implement the accepted event vocabulary and migration so generated events carry stable structured
meaning and metrics no longer depend on user-facing message substrings.

## Baseline and authority

Refresh `origin/main`, inspect the live issue and migration head, and inventory every event writer,
reader, export, and metric. Stop while the issue is pending or its vocabulary is undecided.

## Scope

Add accepted kind/payload fields, write them at all generated-event paths, migrate safely, update
metrics/exports, and handle legacy/manual rows explicitly.

## Non-goals

No telemetry, analytics service, historical-message rewrite, or guessed classification of
ambiguous legacy rows.

## Interfaces and data flow

The live issue must define kind values, payload schemas, API serialization, and legacy behavior.
All event data stays in the local database.

## Safety and approval gates

Preserve messages, dates, actors, evidence, attachments, and links. Use a new linear `oss_NNNN`
revision and update required migration test catalogs; never edit pinned revisions or lineage.

## Implementation steps

Pin current metric behavior with tests; add the migration/model/schema; update writers before
readers; convert metric/funnel/export code; cover mixed legacy/new data; update provenance docs.

## Verification

Run focused and full host backend tests plus Ruff. Migration round trips and disposable-stack tests
require explicit per-run approval.

## Documentation and evidence

Open a review-ready PR describing the vocabulary, compatibility, preservation proof, commands, and
checks not run. Keep metric claims tied to recorded tests.

## Stop conditions

Stop for an unrecorded vocabulary/API decision, destructive backfill, guarded verification without
approval, or before merge/maintainer gate.
