# decompose correspondence-contract implementation

> Draft only. Do not publish without explicit maintainer approval.

## User problem and intended outcome

The accepted correspondence contract must become bounded implementation work without risking
duplicates, gaps, or loss of user edits. Outcome: an approved decomposition fixes shared types,
storage boundaries, Gmail recovery behavior, and lifecycle preservation before coding begins.

## Current state

`docs/CORRESPONDENCE_CAPABILITY.md` maps Gmail gaps, including missing mailbox namespaces,
continuations, overlap guarantees, per-connection checkpoints, and shared error mappings. The
contract still awaits acceptance in #24. Reviewed at commit `f9024aa` (`main`) on 2026-11-23.

## Scope

Specify children for: shared adapter types and a synthetic conformance harness; provider/mailbox
identity and checkpoint storage; Gmail paging, late-delivery, 404, and recovery behavior; and
retry/disconnect/provider-switch preservation coordinated with #11.

## Non-goals

No adapter implementation, migration, second provider, mailbox write, or sending in this issue.

## Capabilities and data flows

Correspondence: read. Provider data flows into local normalized records only; no processor or
other provider receives it.

## Dependencies and unresolved decisions

Blocked by acceptance of #24. Resolve coexistence with `gmail_message_id`, stable mailbox identity,
checkpoint ownership, and connection cardinality before filing implementation children.

## Acceptance criteria

- Each child has one migration-safe outcome, explicit interfaces, failure semantics, and tests.
- The sequence prevents a new adapter from depending on Gmail-specific storage.
- Duplicate, late, deleted, partial-page, revoked, and provider-switch cases are assigned once.
- #11 lifecycle behavior is referenced rather than duplicated.

## Security, privacy, failure handling and data preservation

Message content remains untrusted and absent from logs. Imported records, user edits, links, and
detection survive retries and provider changes. Any future schema change uses a new `oss_NNNN`.

## Evidence expected

Reviewed design/decomposition mapped clause-by-clause to the accepted contract.

## Documentation affected

Correspondence contract, roadmap, work program, and later issue bodies.

## Contributor notes

- Suggested branch: `docs/correspondence-implementation-plan` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: correspondence docs, storage and adapter boundaries.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: #3.
- Dependency: #24.
- Actual branch and pull request: not created yet.
- Verification evidence: pending.
