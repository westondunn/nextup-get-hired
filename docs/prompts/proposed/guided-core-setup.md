---
work_id: proposed-guided-core-setup
status: proposed
issue: pending
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.1-terra
depends_on: live-28-core-onboarding-acceptance,discovery-initial-platform-and-packaging-decision
approval_gates: issue-publication,full-verification,platform-validation
canonical_sources: docs/CORE_ONBOARDING.md,scripts/local.py,docs/decisions/0001-local-session-boundary.md,docs/planning/issue-drafts/guided-core-setup.md
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Implement guided core setup

## Outcome

Implement the accepted setup path for the selected platform with retryable, data-preserving failure behavior.

## Baseline and authority

Stop unless the issue is live and the packaging ADR is accepted. Re-read launcher/guard contracts from fresh `origin/main`.

## Scope

Implement prerequisite check, preparation, guarded migration review, progress/retry, open, and stop behavior; reuse existing guarded primitives.

## Non-goals

No integration/AI setup, automatic reset, remote binding, migration bypass, or unsupported platform.

## Interfaces and data flow

Define setup state, retry state, redacted errors, installation identity, dependency destinations, and local URLs exactly as accepted.

## Safety and approval gates

Preserve loopback, restricted secret files, confirmation input, and volumes. Full verification requires per-run approval.

## Implementation steps

Add tests first for cancellation/interruption/retry, implement the narrow path, update docs, and open a review-ready PR.

## Verification

Run unit/lint/build checks; use Terra Ultra for interactive keyboard/visual validation. Do not claim clean-machine success here.

## Documentation and evidence

Record commands, failure paths, unrun checks, and forward-fix/rollback limits.

## Stop conditions

Stop on uncertain identity/migration state, required destructive reset, or any unapproved platform expansion.
