---
work_id: live-23-interoperability-acceptance
status: live
issue: 23
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.2-sol
depends_on: none
approval_gates: maintainer-decision, issue-update, issue-close
canonical_sources: docs/decisions/0002-standards-first-interoperability.md, docs/ROADMAP.md, docs/INTEGRATIONS.md, https://github.com/westondunn/nextup-get-hired/issues/23
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Prepare the interoperability policy for maintainer acceptance

## Outcome

The maintainer receives a concise evidence-backed accept/amend recommendation for decision 0002;
only the maintainer sets its final status.

## Baseline and authority

Refresh `origin/main`, issue #23, decision 0002, README, roadmap, release checklist, integration
matrix, and delivered work for #24, #26, #27, and #28. Treat recorded evidence and current public
claims as the review surface.

## Scope

- Check that agreed direction is separated from unresolved technical choices.
- Search canonical documents and wiki drafts for the issue's excluded claims.
- List remaining decisions, owners, and tracking issues without resolving them implicitly.
- Draft an acceptance or amendment recommendation and exact status-recording changes.

## Non-goals

Do not accept the ADR, choose protocols/providers, implement an adapter, publish the wiki, or close
the issue without the maintainer's explicit decision.

## Interfaces and data flow

No runtime change. Verify that capability vocabulary keeps mail read, calendar read, AI processing,
workflow access, and sending separate, with explicit destinations and consent.

## Safety and approval gates

Use public repository evidence only. Preserve the ban on silent data transfer/fallback and automatic
outbound or consequential actions. A model recommendation is not maintainer acceptance.

## Implementation steps

1. Produce a clause-to-document audit and excluded-claim search results.
2. Present accept/amend choices with concrete edits and remaining open decisions.
3. Stop for the maintainer's decision.
4. After explicit acceptance, record status and evidence on a `docs/` branch and open a PR.

## Verification

Run link/path checks, focused text searches, Markdown checks, and `git diff --check`. No runtime or
integration test is required for the decision record.

## Documentation and evidence

Update decision 0002 and its canonical cross-references only after acceptance. Prepare the issue
comment/closure text separately; publication requires approval.

## Stop conditions

Stop for any unresolved contradiction, excluded public claim, missing maintainer decision, or change
that would silently select an implementation technology.
