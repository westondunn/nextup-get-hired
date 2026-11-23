---
work_id: discovery-ai-implementation-decomposition
status: discovery
issue: pending
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.2-sol
depends_on: proposed-core-public-preview-tracker
approval_gates: issue-publication,architecture-acceptance
canonical_sources: docs/planning/issue-drafts/ai-implementation-decomposition.md,docs/AI_TASK_CONTRACT.md,docs/CORRESPONDENCE_SYNC.md
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Decompose the optional classification-hint implementation

## Outcome

Turn the completed AI task contract into separately reviewable consent, adapter, async-integration,
and evaluation specifications while keeping implementation outside the core milestone.

## Baseline and authority

Refresh `origin/main`, read the live approved discovery issue and both classifier contracts, and
verify that no processor is currently enabled. Stop while the issue is pending.

## Scope

Specify storage/provenance, exact endpoint and credential boundaries, strict request/response
validation, job triggering, failure semantics, fixture/version rules, metrics, and support evidence.

## Non-goals

No code, provider choice, general assistant, tools, URL following, automatic correspondence or
applications, or claim that a consumer subscription works.

## Interfaces and data flow

Use only the bounded subject/excerpt and hint-or-abstain shapes in the contract. Record explicit
consent for the exact task, endpoint, model, fields, and limits; no silent fallback.

## Safety and approval gates

Mail access is not AI consent. Failure or abstention writes no new hint and preserves rule/manual
workflows. Provider changes do not replay history. Architecture acceptance precedes child issues.

## Implementation steps

Map contract clauses to four proposed children; make schemas, migrations, queues, provenance, and
tests explicit; freeze evaluation semantics before suggesting thresholds; remove overlap.

## Verification

Review synthetic injection, invalid-output, timeout, unsupported-company, consent-revocation, and
provider-switch scenarios. Do not connect to a model endpoint.

## Documentation and evidence

Open a review-ready documentation PR with the decomposition and remaining decisions. Connectivity
and quality evidence must remain separate.

## Stop conditions

Stop before implementation, provider/account use, issue publication, merge, or any unreviewed data
egress/retention decision.
