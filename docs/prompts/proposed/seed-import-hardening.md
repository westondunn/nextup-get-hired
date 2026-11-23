---
work_id: proposed-seed-import-hardening
status: proposed
issue: pending
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.2-sol
depends_on: proposed-core-public-preview-tracker
approval_gates: issue-publication,full-verification
canonical_sources: docs/planning/issue-drafts/seed-import-hardening.md,backend/app/seed_import.py,docs/CORE_ONBOARDING.md
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Make seed import preview and apply one bounded operation

## Outcome

Implement the approved seed-import issue so preview and apply consume one strict plan and retries
or failures cannot duplicate records, misreport work, or overwrite user edits.

## Baseline and authority

Start from a clean current `origin/main`, read the live approved issue and repository instructions,
and compare them with the draft and current seed code. The live issue controls. Stop if `issue` is
still pending or if the accepted behavior of `lead_reconciliation` is not recorded.

## Scope

Add bounded schemas, a side-effect-free planner, truthful preview, atomic apply, idempotent retry,
fixed safe errors, and synthetic tests for every supported record and reference.

## Non-goals

Do not redesign onboarding, fetch seeds remotely, reset campaigns, or broaden the accepted format
without an issue amendment.

## Interfaces and data flow

Keep `/api/seed/preview` and `/api/seed/apply` local. Record the exact accepted schema and limits in
the issue before changing them. Nothing leaves NextUp.

## Safety and approval gates

Preserve terminal tasks, confirmed evidence, user edits, and relationships. Never log submitted
content. A schema change requires a new `oss_NNNN`; never edit pinned revisions or
`LINEAGE.sha256`. Ask before guarded full verification.

## Implementation steps

Reproduce preview/apply divergence in tests; define the planner and validation once; make preview
serialize the plan and apply execute it in one transaction; remove the unused deprecated model;
update the documented format; keep the diff limited to the accepted issue.

## Verification

Run focused unit tests, backend unit tests, Ruff check/format check, and script/frontend checks only
if touched. Request per-run permission before `NEXTUP_INTEGRATION_APPROVED=1 scripts/verify.sh`.

## Documentation and evidence

Open a review-ready PR using the template with commands, skipped checks, preservation evidence,
and the issue link. Do not claim the guided setup now depends on seed JSON.

## Stop conditions

Stop before publishing an issue, full verification without permission, merge, maintainer approval,
or any choice that changes the approved seed contract.
