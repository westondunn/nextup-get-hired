---
work_id: proposed-reconcile-live-repository-rules
status: proposed
issue: pending
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.2-sol
depends_on: proposed-governance-execution-tracker
approval_gates: issue-publication,ruleset-mutation
canonical_sources: docs/BRANCHING.md,docs/DEVELOPMENT.md,CONTRIBUTING.md,.github/workflows/maintainer-approval.yml,docs/planning/issue-drafts/reconcile-live-repository-rules.md
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Reconcile governance documents with live rules

## Outcome

Make checked-in governance guidance match the effective live rules while changing no rule.

## Baseline and authority

From fresh `origin/main`, read the live issue, every active ruleset through the read-only API, the approval workflow, and all affected documents. Date every live-state observation.

## Scope

Correct statements about required statuses, PRs, bypass, deletion, non-fast-forward updates, linear history, and tags; preserve historical evidence as historical.

## Non-goals

No ruleset, permission, workflow behavior, branch, tag, merge, or approval mutation.

## Interfaces and data flow

Read-only GitHub metadata becomes public documentation. No application data is involved.

## Safety and approval gates

If the issue remains pending, stop. Any configuration change requires a separate issue and explicit approval.

## Implementation steps

Build an evidence table, identify contradictions, apply the narrow documentation corrections, and open a review-ready PR.

## Verification

Re-read live configuration after edits, check links and terminology, run planning validation, and run `git diff --check`.

## Documentation and evidence

Record rule IDs, inspection date, source commit, and exact checks without secrets.

## Stop conditions

Stop if effective rules cannot be read, sources conflict, or a fix would require mutation rather than documentation.
