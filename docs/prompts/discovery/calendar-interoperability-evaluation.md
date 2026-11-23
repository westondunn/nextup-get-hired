---
work_id: discovery-calendar-interoperability-evaluation
status: discovery
issue: pending
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.2-sol
depends_on: proposed-core-public-preview-tracker
approval_gates: issue-publication,live-service-use
canonical_sources: docs/planning/issue-drafts/calendar-interoperability-evaluation.md,docs/INTEGRATIONS.md,backend/app/sources/google_calendar.py
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Evaluate calendar interoperability beyond Google

## Outcome

Recommend one bounded next calendar capability—or explicit deferral—using consistent criteria and
current primary sources.

## Baseline and authority

Refresh `origin/main`, read the approved live issue and integration policy, and recheck the Google
adapter/validation baseline. Stop while the issue is pending.

## Scope

Compare iCalendar file exchange, CalDAV read access, and one second provider API for permissions,
identity, recurrence/time-zone fidelity, incremental sync, deletions, setup, and test cost.

## Non-goals

No implementation, calendar writes, automatic scheduling, universal compatibility claim, or live
personal calendar.

## Interfaces and data flow

Keep Calendar: read separate from Calendar: file import or export. Record credentials, destinations,
retention, and what stays local for each candidate.

## Safety and approval gates

Flag broad grants and unknown retention. Provider changes preserve local records and edits. Any
controlled experiment needs explicit approval and cannot establish support by itself.

## Implementation steps

Lock criteria and shortlist; research primary specifications/provider docs with review dates;
score each candidate; document uncertainty; recommend one path or no work.

## Verification

Cross-check citations and scenario coverage for recurrence, DST, deletion, outage, and revoked
credentials. Use synthetic fixtures or controlled local servers only.

## Documentation and evidence

Open a review-ready evaluation PR. Update the integrations matrix only after recommendation
acceptance and never assign support status from research.

## Stop conditions

Stop before implementation, live service use, issue publication, merge, or unsupported claims.
