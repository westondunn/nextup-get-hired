# decide the workflow, API, and MCP access boundary

> Draft only. Do not publish without explicit maintainer approval.

## User problem and intended outcome

Optional tools need a narrow way to work with NextUp without becoming trusted database clients or
silently taking consequential actions. Outcome: an ADR chooses the first versioned access boundary
and its authorization, scopes, approval, audit, and compatibility rules.

## Current state

The roadmap mentions a possible versioned API, n8n, and MCP, but no interface, authentication,
tool, or issue exists. The current local API is unauthenticated and must not be exposed. Reviewed at
commit `f9024aa` (`main`) on 2026-11-23.

## Scope

Define use cases, read/write scopes, local authentication, CSRF/host interaction, versioning,
idempotency, rate/bounds, audit records, approval of messages/applications, and whether the first
client should be a reference workflow or MCP server.

## Non-goals

No implementation, remote access, hosted service, database credential sharing, automatic sending,
or automatic job applications.

## Capabilities and data flows

Workflow access. The ADR must enumerate every record and destination; NextUp remains authoritative.

## Dependencies and unresolved decisions

Core public preview first. Decide whether any write capability is needed initially and how a local
client is distinguished from an arbitrary web page before implementation issues exist.

## Acceptance criteria

- The ADR selects one bounded first interface or recommends deferral.
- Threat model, permission scopes, approval gates, compatibility, and failure behavior are explicit.
- MCP, n8n, and direct API clients are compared without assuming they share security properties.
- Follow-up issues are filed only after maintainer acceptance.

## Security, privacy, failure handling and data preservation

Never weaken loopback binding or call the current boundary authentication. Consequential actions
remain draft/approval gated, idempotent, auditable, and recoverable.

## Evidence expected

Architecture review, synthetic threat cases, and current primary-source protocol documentation.

## Documentation affected

New ADR, roadmap, integrations matrix, security limits, and release gates if implemented.

## Contributor notes

- Suggested branch: `docs/workflow-access-adr` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: decisions and future API boundary.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: #3.
- Actual branch and pull request: not created yet.
- Verification evidence: pending.
