---
work_id: proposed-app-accessibility-baseline
status: proposed
issue: pending
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.1-terra
depends_on: proposed-core-public-preview-tracker
approval_gates: issue-publication,manual-accessibility-validation,full-verification
canonical_sources: docs/CORE_ONBOARDING.md,frontend/src/,frontend/tests/,docs/planning/issue-drafts/app-accessibility-baseline.md
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Establish the core accessibility baseline

## Outcome

Define and implement consistent names, dialog semantics, focus behavior, announcements, keyboard operation, zoom, and reflow across core workflows.

## Baseline and authority

Stop until a live issue exists. Inventory current UI and existing tests from fresh `origin/main`; keep #12 Google-specific work separate.

## Scope

Repair core modal/drawer/focus/icon-control patterns, prefer shared primitives where safe, and add automated plus manual coverage.

## Non-goals

No visual redesign, formal certification claim, or duplication of #12.

## Interfaces and data flow

Frontend interaction semantics only; no new network or storage interface.

## Safety and approval gates

Use synthetic data. Manual assistive-technology validation is a distinct evidence step; full verification needs opt-in.

## Implementation steps

Publish an inventory, lock expected behavior in tests, implement narrow repairs, perform Terra-assisted validation, and open a PR.

## Verification

Run affected component tests, full frontend checks, keyboard browser checks when approved, and manual screen-reader/zoom/reflow protocol.

## Documentation and evidence

Record tested surfaces, tools, remaining gaps, and avoid unsupported conformance claims.

## Stop conditions

Stop if a shared refactor risks unrelated behavior without tests or validation cannot be performed honestly.
