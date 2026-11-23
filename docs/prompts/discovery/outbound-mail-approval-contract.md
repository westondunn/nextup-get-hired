---
work_id: discovery-outbound-mail-approval-contract
status: discovery
issue: pending
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.2-sol
depends_on: proposed-core-public-preview-tracker
approval_gates: issue-publication,contract-acceptance,external-message
canonical_sources: docs/planning/issue-drafts/outbound-mail-approval-contract.md,docs/CORRESPONDENCE_CAPABILITY.md,docs/INTEGRATIONS.md
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Define the outbound-mail approval contract

## Outcome

Produce a transport-neutral contract that keeps drafting, human approval, submission, retry, and
delivery evidence distinct before any sending technology is evaluated.

## Baseline and authority

Refresh `origin/main`, read the approved issue, correspondence contracts, and user approval
boundary. Confirm no sending capability exists. Stop while the issue is pending.

## Scope

Define draft ownership, immutable approval snapshots, exact recipient/content review, attachments,
explicit send, idempotency, ambiguous outcomes, retry, provenance, cancellation, and audit limits.

## Non-goals

No provider/SMTP choice, implementation, bulk mail, automatic follow-up, automatic application,
or permission inferred from mailbox read or AI consent.

## Interfaces and data flow

Specify conceptual state transitions and the data a future transport/recipient receives. AI output
is untrusted draft content and cannot authorize itself.

## Safety and approval gates

Never send an external message during this task. Preserve drafts and approval evidence on failure;
do not log credentials, recipients, or bodies. Contract acceptance precedes transport research.

## Implementation steps

Walk synthetic success, duplicate, timeout, ambiguous delivery, edit-after-approval, attachment,
and revocation cases; define state invariants and evidence; compare with existing durable intents.

## Verification

Review every consequential transition against the explicit-approval rule. No live mailbox or
transport is used.

## Documentation and evidence

Open a review-ready contract PR and leave sending deferred until accepted.

## Stop conditions

Stop before external communication, implementation, issue publication, transport selection, merge,
or any relaxation of per-message approval.
