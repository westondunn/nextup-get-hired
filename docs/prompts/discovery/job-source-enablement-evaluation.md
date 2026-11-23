---
work_id: discovery-job-source-enablement-evaluation
status: discovery
issue: pending
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.2-sol
depends_on: proposed-core-public-preview-tracker
approval_gates: issue-publication,live-provider-use,configuration-change
canonical_sources: docs/planning/issue-drafts/job-source-enablement-evaluation.md,docs/INTEGRATIONS.md,backend/app/sources
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Evaluate safe enablement of existing job sources

## Outcome

Recommend a provider-specific, off-by-default implementation and validation sequence for Adzuna,
Greenhouse, Lever, and Ashby, or recommend keeping selected adapters disabled.

## Baseline and authority

Refresh `origin/main`, read the approved issue, adapter/configuration code, support policy, and
provider documentation. Confirm all shipped configurations still refuse live fetching. Stop while
the issue is pending.

## Scope

Inventory switches, settings, credentials, request fields, pagination/bounds, quotas, incomplete
results, errors, disconnect, preservation, controlled validation, and evidence per provider.

## Non-goals

No code, live fetch, scraping, credential, support claim, automatic application, or assumption that
shared code makes providers equivalent.

## Interfaces and data flow

For each Job listings: fetch provider, record the exact profile/search fields or board tokens sent,
authentication, retention, and local records produced.

## Safety and approval gates

Keep providers off by default and manual workflows available. Live provider use and configuration
changes require separate approval. Preserve saved jobs, ratings, links, and edits on failure.

## Implementation steps

Reconcile code/configuration; research current primary docs; score providers consistently; select
the smallest safe first slice; define separate implementation and validation children.

## Verification

Use mocked/fixture evidence and source inspection only. Explicitly distinguish code, connectivity,
and support evidence.

## Documentation and evidence

Open a review-ready evaluation PR. Do not alter support status or publish a setup path before later
dated validation.

## Stop conditions

Stop before live calls, implementation, issue publication, configuration enablement, merge, or an
unsupported provider claim.
