---
work_id: proposed-governance-execution-tracker
status: proposed
issue: pending
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.2-sol
depends_on: none
approval_gates: issue-publication,github-mutation
canonical_sources: docs/WORK_PROGRAM.md,docs/ROADMAP.md,docs/planning/issue-drafts/governance-execution-tracker.md
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Track governance and execution-program work

## Outcome

Publish and maintain the approved governance tracker without duplicating canonical status.

## Baseline and authority

Re-read the live issue, `docs/WORK_PROGRAM.md`, roadmap, release checklist, and current GitHub configuration from a fresh `origin/main`. The live issue controls scope.

## Scope

Record approved children, dependencies, evidence links, and closure state. Keep detailed acceptance criteria in each child.

## Non-goals

Do not implement product work or change repository rules, permissions, workflows, or issue state not explicitly authorized.

## Interfaces and data flow

Documentation and public repository metadata only; no NextUp user data.

## Safety and approval gates

If `issue` is still `pending`, stop. Creating or editing GitHub issues requires explicit approval. Never run the maintainer-approval workflow or merge.

## Implementation steps

Reconcile the tracker against live children, update only approved documentation, create a compliant branch, and open a review-ready PR.

## Verification

Run planning-pack validation, link checks, relevant script tests, and `git diff --check`.

## Documentation and evidence

Record the reviewed commit, issue links, checks run, and checks not run.

## Stop conditions

Stop on conflicting canonical sources, unapproved external mutation, or any request to merge.
