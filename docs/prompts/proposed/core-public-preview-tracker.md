---
work_id: proposed-core-public-preview-tracker
status: proposed
issue: pending
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.2-sol
depends_on: live-23-interoperability-acceptance,live-28-core-onboarding-acceptance
approval_gates: issue-publication,public-support-claims
canonical_sources: docs/CORE_ONBOARDING.md,docs/ROADMAP.md,docs/RELEASE_CHECKLIST.md,docs/planning/issue-drafts/core-public-preview-tracker.md
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Track the core-only public preview

## Outcome

Coordinate the accepted core-first milestone with optional connections and AI kept outside its gate.

## Baseline and authority

Refresh `origin/main`, read the live tracker and accepted #23/#28 decisions, then compare every child with the roadmap and checklist.

## Scope

Track platform choice, guided setup, first-run UX, accessibility, browser evidence, clean-machine validation, and representative-user evidence.

## Non-goals

No product implementation in the tracker and no unsupported platform, one-click, production-ready, or integration-support claim.

## Interfaces and data flow

Core local workflows; dependency downloads are distinct from job-search-data egress.

## Safety and approval gates

Stop if the issue is pending or #23/#28 are not explicitly accepted. Public claims require linked dated evidence.

## Implementation steps

Publish approved children, update the ordered roadmap only with live IDs, and open a review-ready documentation PR.

## Verification

Validate links, dependency ordering, off-state claims, issue state, and planning schema.

## Documentation and evidence

Keep release evidence in the checklist and detailed scope in children.

## Stop conditions

Stop on unresolved platform/packaging choices, missing acceptance, or pressure to treat a target as evidence.
