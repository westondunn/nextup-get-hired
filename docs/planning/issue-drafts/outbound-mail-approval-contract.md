# define the outbound-mail approval contract before choosing a transport

> Draft only. Do not publish without explicit maintainer approval.

## User problem and intended outcome

A user may eventually want correspondence assistance, but no tool may send on their behalf without
review. Outcome: a capability contract defines drafting, approval, submission, retry, identity,
audit, and preservation boundaries before SMTP or a provider API is evaluated.

## Current state

NextUp imports correspondence read-only. Sending is deferred with no code, contract, provider, or
issue. Reviewed at commit `f9024aa` (`main`) on 2026-11-23.

## Scope

Define draft ownership, immutable approval snapshot, recipient/attachment review, explicit send
action, idempotency, ambiguous-delivery handling, retry, sent-record provenance, cancellation, and
separation from AI generation and mailbox-read permission.

## Non-goals

No transport selection, implementation, automatic follow-up, bulk mail, automatic sending, or
authorization inferred from a mailbox connection.

## Capabilities and data flows

Correspondence: send. The contract must enumerate the eventual transport and recipients as data
destinations; no destination is selected here.

## Dependencies and unresolved decisions

Core release and read-only correspondence remain independent. Transport evaluation begins only
after this contract is accepted.

## Acceptance criteria

- Every send requires explicit review of exact recipients and immutable content.
- Retries cannot duplicate delivery and ambiguous outcomes never claim success.
- AI output remains an untrusted draft and cannot approve itself.
- Audit and rollback limits are stated without storing credentials or message bodies in logs.

## Security, privacy, failure handling and data preservation

Preserve drafts, approval evidence, and authoritative records on failure. Never authorize external
messages or applications implicitly.

## Evidence expected

Contract review using synthetic failure and duplicate-delivery scenarios.

## Documentation affected

New capability contract, roadmap, integrations vocabulary, and later release gates.

## Contributor notes

- Suggested branch: `docs/outbound-mail-contract` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: correspondence and security documentation.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: #3.
- Actual branch and pull request: not created yet.
- Verification evidence: pending.
