---
work_id: proposed-today-commitments-followups
status: proposed
issue: pending
primary_model: gpt-6.2-sol
reasoning_effort: ultra
validation_model: gpt-6.2-sol
depends_on: none
approval_gates: issue-publication
canonical_sources: frontend/src/hub/TodayView.tsx,frontend/src/hub/campaign-api.ts,docs/planning/issue-drafts/today-commitments-followups.md
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Fix Today commitments and follow-ups rendering

## Outcome

Make the section visibility and rendered collections consistent, with regression tests for each collection alone and together.

## Baseline and authority

Stop until a live issue exists. Re-read the API type, Today component, and current tests before deciding whether commitments need their own rendering.

## Scope

Resolve the contract, make the smallest component change, and add focused synthetic tests.

## Non-goals

No Today redesign, task scheduling change, API expansion, or unrelated refactor.

## Interfaces and data flow

Existing Today response only; presentation changes do not mutate data.

## Safety and approval gates

Preserve existing interview/follow-up behavior and use synthetic fixtures.

## Implementation steps

Write failing cases, implement the resolved behavior, run frontend checks, update issue evidence, and open a PR.

## Verification

Run focused Vitest, all frontend tests, typecheck, build, format check, and `git diff --check`.

## Documentation and evidence

Explain the chosen commitment behavior and list every test result in the PR.

## Stop conditions

Stop if the backend contract is ambiguous enough to require a product decision not recorded in the live issue.
