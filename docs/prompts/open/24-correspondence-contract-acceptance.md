---
work_id: live-24-correspondence-contract-acceptance
status: live
issue: 24
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.2-sol
depends_on: live-23-interoperability-acceptance
approval_gates: maintainer-decision, issue-update, issue-close
canonical_sources: docs/CORRESPONDENCE_CAPABILITY.md, docs/INTEGRATIONS.md, docs/decisions/0002-standards-first-interoperability.md, https://github.com/westondunn/nextup-get-hired/issues/24
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Prepare the correspondence contract for maintainer acceptance

## Outcome

The maintainer receives a clause-by-clause review of the merged read-only correspondence contract,
its Gmail mapping, open gaps, and a precise accept/amend recommendation that can unblock #25.

## Baseline and authority

Refresh issue #24, PR #65, PR #69, the contract, current Gmail adapter/worker/storage, classifier
contract, and hosted evidence. Reconcile the issue's stale “no pull request” baseline.

## Scope

- Verify normalized fields, namespaced identity, permissions, cursors, errors, preservation, and
  required synthetic tests are internally consistent and accurately map Gmail.
- Identify gaps as future implementation work rather than silently changing current behavior.
- Draft acceptance/status updates and a bounded implementation-decomposition handoff.

## Non-goals

No adapter refactor, migration, second-provider evaluation, classifier-key rename, Gmail behavior
change, or contract acceptance by the model.

## Interfaces and data flow

Review only the proposed provider-to-adapter-to-local-storage read path. Preserve the separation
between mailbox permission and AI consent; imported content goes to no other processor here.

## Safety and approval gates

Use synthetic/public evidence. Do not approve broader credentials, sending, destructive resync, or
loss of user edits. Only the maintainer can accept and close #24.

## Implementation steps

1. Map each acceptance criterion to contract text and Gmail evidence.
2. List contradictions, underspecified clauses, and implementation gaps separately.
3. Present accept/amend wording and stop for the maintainer.
4. After acceptance, record status/evidence in a review-ready documentation PR.

## Verification

Run Markdown/link checks and targeted static comparisons to current code. No provider or full-stack
run is required for accepting a documentation contract.

## Documentation and evidence

Update the contract status, roadmap evidence, integration cross-reference, and issue record only
after the decision. State that future adapters still require conformance evidence.

## Stop conditions

Stop for unresolved data-preservation semantics, identity/classifier conflicts that change the
contract, an absent #23 decision where it matters, or missing maintainer acceptance.
