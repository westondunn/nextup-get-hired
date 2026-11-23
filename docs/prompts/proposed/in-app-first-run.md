---
work_id: proposed-in-app-first-run
status: proposed
issue: pending
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.1-terra
depends_on: live-28-core-onboarding-acceptance,proposed-core-public-preview-tracker
approval_gates: issue-publication,full-verification
canonical_sources: docs/CORE_ONBOARDING.md,frontend/src/NextupHub.tsx,frontend/src/hub/,docs/planning/issue-drafts/in-app-first-run.md
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Implement the in-app first-run path

## Outcome

Let an empty-workspace user start all six core workflows without seed JSON, integrations, or AI.

## Baseline and authority

Stop until the issue is live and #28 is accepted. Re-audit current empty states, APIs, and tests before editing.

## Scope

Add direct application/job paths, campaign creation, optional profile setup, actionable empty states, and durable dismissal/completion behavior.

## Non-goals

No automatic applications, outbound messages, provider setup, or broad visual redesign.

## Interfaces and data flow

Reuse or explicitly define local APIs for applications, campaigns, tasks, contacts, résumés, jobs, and profile. No external egress.

## Safety and approval gates

Preserve existing records and safe URL rendering. Full browser verification needs explicit per-run approval.

## Implementation steps

Write empty/populated/failure tests, implement in reviewable slices, add accessibility behavior, update docs, and open a PR.

## Verification

Run affected Vitest, frontend test/typecheck/build/format checks; use Terra Ultra for keyboard/focus/visual review.

## Documentation and evidence

Map each visible action to the onboarding workflow table and list what remains for E2E evidence.

## Stop conditions

Stop if a needed API contract is undecided, a change would overwrite user state, or scope expands into integrations.
