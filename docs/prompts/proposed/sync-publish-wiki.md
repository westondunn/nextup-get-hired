---
work_id: proposed-sync-publish-wiki
status: proposed
issue: pending
primary_model: gpt-6.2-sol
reasoning_effort: ultra
validation_model: gpt-6.2-astra
depends_on: proposed-governance-execution-tracker
approval_gates: issue-publication,wiki-publication
canonical_sources: docs/wiki/README.md,docs/wiki/,README.md,docs/ROADMAP.md,docs/INTEGRATIONS.md,docs/planning/issue-drafts/sync-publish-wiki.md
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Synchronize and publish wiki summaries

## Outcome

Bring repository wiki drafts up to date, then publish only after a separate explicit approval and record the revision.

## Baseline and authority

Stop until the issue is live and canonical documents are merged. Compare current wiki revision, draft status, and canonical sources.

## Scope

Update concise Home/Roadmap/Integrations drafts, convert links for wiki use, prepare a diff, and after approval publish and record evidence.

## Non-goals

No wiki-originated status, acceptance criterion, support claim, or publication before approval.

## Interfaces and data flow

Approved public Markdown is copied to the separate GitHub wiki repository.

## Safety and approval gates

Draft PR and wiki publication are separate actions. Never push the wiki without explicit approval after review.

## Implementation steps

Reconcile drafts, validate links/claims, open draft-source PR, pause, publish approved pages, verify them, then open recording PR.

## Verification

Check every link and source commit; Astra reviews claim accuracy. Record checks not run.

## Documentation and evidence

Update source commit, synchronization date, wiki revision, and page status.

## Stop conditions

Stop on unsettled canonical sources, unverified claims, unrelated wiki changes, or missing publication approval.
