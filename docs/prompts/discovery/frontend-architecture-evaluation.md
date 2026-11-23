---
work_id: discovery-frontend-architecture-evaluation
status: discovery
issue: pending
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.1-terra
depends_on: proposed-core-public-preview-tracker,proposed-in-app-first-run
approval_gates: issue-publication,browser-validation
canonical_sources: docs/planning/issue-drafts/frontend-architecture-evaluation.md,frontend/src/NextupHub.tsx,docs/CORE_ONBOARDING.md
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Evaluate frontend navigation, loading, and view boundaries

## Outcome

Produce a review-ready evaluation that recommends one bounded URL/history approach and an ordered
loading/module cleanup, or recommends deferral.

## Baseline and authority

Refresh current `origin/main`, read the approved live issue, measure the production build, map shell
navigation/tests, and verify apparent orphan views before drawing conclusions. Stop if no issue has
been approved.

## Scope

Evaluate deep links, refresh/back-forward behavior, Google callback compatibility, code splitting,
large-view ownership, and unused views. Propose separate implementation children.

## Non-goals

Do not implement a router, redesign UI, delete views, or choose a framework in this task.

## Interfaces and data flow

Document the proposed URL contract and what must never enter URLs or browser storage. No new data
destination is introduced.

## Safety and approval gates

Preserve loopback proxy behavior, safe callback result handling, accessibility, and testability.
Interactive validation may use Terra Ultra with synthetic data only.

## Implementation steps

Collect static and build measurements; exercise navigation paths; compare minimal alternatives;
record tradeoffs and migration/testing steps; draft children only after selecting a recommendation.

## Verification

Run frontend typecheck, production build, unit tests, and non-mutating browser probes available
without a stack. State clearly when interactive or full-stack behavior was not run.

## Documentation and evidence

Open a documentation PR containing the evaluation and measured evidence. Do not change the roadmap
to implementation until the maintainer accepts the recommendation.

## Stop conditions

Stop before code implementation, destructive cleanup, unapproved browser/full-stack work, issue
publication, merge, or maintainer approval.
