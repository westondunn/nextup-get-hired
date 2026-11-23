---
work_id: discovery-correspondence-implementation-decomposition
status: discovery
issue: pending
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.2-sol
depends_on: live-24-correspondence-contract-acceptance
approval_gates: issue-publication,architecture-acceptance
canonical_sources: docs/planning/issue-drafts/correspondence-implementation-decomposition.md,docs/CORRESPONDENCE_CAPABILITY.md,docs/CORRESPONDENCE_SYNC.md
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Decompose correspondence-contract implementation

## Outcome

Produce accepted, migration-safe child specifications for shared adapter conformance, namespaced
identity/checkpoints, Gmail recovery, and lifecycle preservation without implementing them.

## Baseline and authority

Refresh `origin/main`, confirm #24 is accepted, read the live issue and both correspondence
contracts, and remap every documented Gmail gap to current code. Stop while #24 or this issue is
pending.

## Scope

Define child order, exact boundaries, storage decisions, error vocabulary, conformance fixtures,
and ownership of duplicate/late/deleted/partial/revoked/provider-switch behavior.

## Non-goals

No code, migration, second adapter, mailbox write, classifier-key rename, or sending.

## Interfaces and data flow

Specify normalized adapter results, provider/mailbox/message identity, checkpoint semantics, and
safe error categories. Correspondence remains provider-to-NextUp only.

## Safety and approval gates

Preserve imported records, edits, links, detection, and provenance. Coordinate disconnect behavior
with #11. Message content stays out of logs. No child is published before architecture acceptance.

## Implementation steps

Audit code against contract clauses; decide and document storage/interface questions; build a
dependency graph; draft one-outcome children with migrations/tests; check no behavior is assigned
twice.

## Verification

Use static code/doc inspection and synthetic scenario walkthroughs. Do not run live providers or
guarded integration verification for this documentation task.

## Documentation and evidence

Open a review-ready documentation PR linking each contract clause to a child or explicit deferral.

## Stop conditions

Stop if #24 is unaccepted, a schema choice lacks maintainer review, or before issue publication,
code changes, merge, or maintainer approval.
