---
work_id: discovery-workflow-api-mcp-boundary
status: discovery
issue: pending
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.2-sol
depends_on: proposed-core-public-preview-tracker
approval_gates: issue-publication,adr-acceptance
canonical_sources: docs/planning/issue-drafts/workflow-api-mcp-boundary.md,docs/ROADMAP.md,docs/decisions/0001-local-session-boundary.md
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Decide the workflow, API, and MCP access boundary

## Outcome

Produce an ADR selecting one bounded first access interface or recommending deferral, with explicit
authorization, versioning, scopes, approval, auditing, and failure behavior.

## Baseline and authority

Refresh `origin/main`, read the approved live issue, current security limits, API surface, and
interoperability policy. The current local session and request boundary are not authentication.
Stop while the issue is pending.

## Scope

Compare versioned HTTP access, a reference workflow client, and MCP; define initial read/write use
cases, local credentials, scopes, CSRF/Host handling, bounds, idempotency, audit, and compatibility.

## Non-goals

No code, network exposure, hosted service, database access, automatic send, automatic application,
or assumption that MCP/n8n/API clients share a trust model.

## Interfaces and data flow

Enumerate every requested record and destination. NextUp stays authoritative and consequential
actions remain drafts requiring explicit user approval.

## Safety and approval gates

Preserve loopback-only publication. Threat-model malicious local web pages, stolen client secrets,
replay, confused deputies, untrusted content, and ambiguous writes. ADR acceptance precedes code.

## Implementation steps

Collect bounded user stories; inventory existing routes; compare alternatives; define security and
compatibility contracts; recommend one minimal read-first slice or deferral; draft later children.

## Verification

Use current primary protocol documentation and synthetic threat walkthroughs. Do not change GitHub
rules, run external clients, or expose a port.

## Documentation and evidence

Open a review-ready ADR PR and keep the roadmap in discovery until explicit acceptance.

## Stop conditions

Stop before implementation, ruleset changes, issue publication, external access, merge, or an
unapproved consequential-action model.
