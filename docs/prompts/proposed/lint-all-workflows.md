---
work_id: proposed-lint-all-workflows
status: proposed
issue: pending
primary_model: gpt-6.2-sol
reasoning_effort: ultra
validation_model: gpt-6.2-sol
depends_on: proposed-governance-execution-tracker
approval_gates: issue-publication,full-verification
canonical_sources: scripts/verify_ci.py,scripts/tests/,.github/workflows/,docs/planning/issue-drafts/lint-all-workflows.md
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Lint every checked-in workflow

## Outcome

Extend the pinned actionlint verification so every current and future workflow is covered deterministically.

## Baseline and authority

Re-read the live issue and current runner/tests from clean `origin/main`; confirm which workflow files exist.

## Scope

Change only workflow discovery/arguments and its contract tests. Preserve the pinned image, read-only mount, and isolation.

## Non-goals

No workflow semantics, permissions, triggers, rulesets, or dependencies change.

## Interfaces and data flow

The verification runner passes repository workflow paths to a pinned local container; no user data.

## Safety and approval gates

Stop if the issue is pending. Do not run full disposable verification without explicit per-run opt-in.

## Implementation steps

Add deterministic discovery, add positive and omission-regression tests, lint/format, then open a review-ready PR.

## Verification

Run focused script tests, full script unit tests, Ruff checks for scripts, planning validation, and `git diff --check`; list guarded verification as not run unless approved.

## Documentation and evidence

Update the verification inventory only if its described coverage changes.

## Stop conditions

Stop if implementation requires editing workflow behavior or using an unpinned executable.
