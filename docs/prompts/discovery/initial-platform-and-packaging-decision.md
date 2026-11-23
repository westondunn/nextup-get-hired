---
work_id: discovery-initial-platform-and-packaging-decision
status: discovery
issue: pending
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.2-sol
depends_on: live-28-core-onboarding-acceptance,proposed-core-public-preview-tracker
approval_gates: issue-publication,adr-acceptance
canonical_sources: docs/CORE_ONBOARDING.md,docs/DEVELOPMENT.md,scripts/local.py,docs/planning/issue-drafts/initial-platform-and-packaging-decision.md
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Decide the first platform and packaging path

## Outcome

Produce a primary-source-backed ADR recommending one minimal initial platform/architecture and delivery path, or recommending delay.

## Baseline and authority

Stop if no live approved issue exists. Refresh repository evidence and current official platform/tool documentation; record review dates.

## Scope

Compare the existing launcher/Compose path with credible packaging options across prerequisites, updates, rollback, data location, accessibility, signing, and maintenance.

## Non-goals

No installer code, platform claim, remote exposure, or safety-boundary change.

## Interfaces and data flow

Document setup inputs, dependency-download destinations, local data ownership, update, and rollback interfaces.

## Safety and approval gates

The maintainer must accept the ADR before implementation. No external installer publication or signing action.

## Implementation steps

Build a consistent scorecard, verify claims with primary sources, recommend one bounded path, draft ADR/docs, and open a review-ready PR.

## Verification

Check source links/dates, reproduce existing doctor/start assumptions read-only where possible, and run documentation validation.

## Documentation and evidence

List excluded platforms and unknowns explicitly; do not convert evaluation into support evidence.

## Stop conditions

Stop if candidates cannot be compared on common criteria or a recommendation would weaken guard, secrets, or loopback requirements.
