---
work_id: proposed-core-workflow-e2e-evidence
status: proposed
issue: pending
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.1-terra
depends_on: proposed-in-app-first-run,proposed-app-accessibility-baseline
approval_gates: issue-publication,full-verification
canonical_sources: docs/CORE_ONBOARDING.md,frontend/tests/,scripts/verify_ci.py,docs/planning/issue-drafts/core-workflow-e2e-evidence.md
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Prove offline core workflows through the UI

## Outcome

Add deterministic browser evidence for all six workflows, reload/restart persistence, and absence of unexpected runtime egress.

## Baseline and authority

Stop if the issue is pending or first-run work is incomplete. Audit existing specs to avoid API-seeded false confidence.

## Scope

Drive visible controls from empty state through application, task, contact, résumé, manual job, and optional profile workflows; reload and restart.

## Non-goals

No live provider, installation validation, personal data, or representative-user claim.

## Interfaces and data flow

Playwright uses the disposable stack and synthetic records. Record outbound connection attempts without payloads.

## Safety and approval gates

Never set `NEXTUP_INTEGRATION_APPROVED=1` without explicit per-run opt-in. Cleanup stays scoped to the disposable project.

## Implementation steps

Add stable fixtures/helpers, tests for persistence and failure, egress observation, evidence docs, and a review-ready PR.

## Verification

Run safe frontend unit/type/build checks first; guarded browser/full verification only after approval. Terra validates interaction quality.

## Documentation and evidence

Link each test to the onboarding matrix and report unrun scenarios separately.

## Stop conditions

Stop on non-disposable targets, required live calls, or any test shortcut that bypasses the user workflow under test.
