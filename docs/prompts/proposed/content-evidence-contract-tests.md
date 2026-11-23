---
work_id: proposed-content-evidence-contract-tests
status: proposed
issue: pending
primary_model: gpt-6.2-sol
reasoning_effort: ultra
validation_model: gpt-6.2-astra
depends_on: proposed-core-public-preview-tracker
approval_gates: issue-publication,full-verification
canonical_sources: docs/planning/issue-drafts/content-evidence-contract-tests.md,backend/app/content.py,backend/app/evidence.py
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Add Content and Evidence contract coverage

## Outcome

Add synthetic integration coverage for the accepted Content and Evidence API behavior, with any
production fix limited to a defect first demonstrated by a regression test.

## Baseline and authority

Refresh `origin/main`, read the live approved issue, enumerate routes and existing résumé coverage,
and stop while the issue remains pending or behavior is ambiguous.

## Scope

Cover CRUD, workflow/state transitions, ordering, task links, validation, conflicts/not-found,
deletion ownership, and preservation across unrelated updates.

## Non-goals

No redesign, arbitrary coverage target, unrelated refactor, or production change without a failing
contract case.

## Interfaces and data flow

Treat the current accepted local API as the interface. Synthetic data stays in isolated disposable
schemas and is never sent elsewhere.

## Safety and approval gates

Keep fixtures synthetic, file bounds and safe URL behavior intact, and migrations unchanged unless
the issue is explicitly amended. Full verification remains per-run approval gated.

## Implementation steps

Build route/behavior matrices; add focused integration modules and reusable synthetic fixtures;
write refusal and preservation cases; implement only proven fixes; keep assertions observable.

## Verification

Run relevant unit collection and Ruff locally. Request approval for the disposable stack needed to
execute integration cases, and record anything not run.

## Documentation and evidence

Open a review-ready PR with the covered contract matrix, failures found, commands, and hosted/full
evidence when authorized.

## Stop conditions

Stop if product semantics need a decision, real data would be required, or before unapproved full
verification, merge, or maintainer approval.
