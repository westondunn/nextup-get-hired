---
work_id: proposed-clean-machine-core-validation
status: proposed
issue: pending
primary_model: gpt-6.1-terra
reasoning_effort: ultra
validation_model: gpt-6.2-astra
depends_on: proposed-guided-core-setup,proposed-in-app-first-run,proposed-core-workflow-e2e-evidence,discovery-initial-platform-and-packaging-decision
approval_gates: issue-publication,clean-machine-use,full-verification,public-support-claims
canonical_sources: docs/CORE_ONBOARDING.md,docs/RELEASE_CHECKLIST.md,docs/planning/issue-drafts/clean-machine-core-validation.md
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Validate core setup on a clean machine

## Outcome

Execute and document the accepted setup from a pristine starting state for the exact platform configuration claimed.

## Baseline and authority

Stop unless the issue is live, dependencies are merged, and the user explicitly authorizes the target machine/VM and guarded runs.

## Scope

Record starting state and versions; exercise setup, recovery cases, six workflows, stop/restart, persistence, and egress behavior.

## Non-goals

No live integration, personal data, unclaimed platform, destructive cleanup, or broader support claim.

## Interfaces and data flow

Terra operates the visible setup/browser surfaces; Astra reviews redacted evidence and claims. Dependency downloads are recorded separately.

## Safety and approval gates

Resolve exact machine and disposable boundaries before acting. Never delete pre-existing data or expose non-loopback services.

## Implementation steps

Preflight, capture redacted baseline, execute the approved script without improvising around refusals, record results, update docs in a PR.

## Verification

Run matching hosted verification if separately approved; confirm retained records after restart and no unexpected egress.

## Documentation and evidence

Record exact commit, OS/architecture, runtime versions, results, failures, assistance, artifacts, and limits.

## Stop conditions

Stop on a non-pristine or ambiguous target, any request for real data, unsafe recovery, or missing per-run approval.
