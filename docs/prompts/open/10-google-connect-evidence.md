---
work_id: live-10-google-connect-evidence
status: live
issue: 10
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.2-sol
depends_on: none
approval_gates: full-verification, issue-close
canonical_sources: docs/decisions/0003-google-connection.md, docs/ROADMAP.md, docs/RELEASE_CHECKLIST.md, https://github.com/westondunn/nextup-get-hired/issues/10
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Audit and record completion evidence for Google connect

## Outcome

Every acceptance criterion in issue #10 is mapped to merged code, tests, and hosted evidence; any
real gap is named precisely. No already-merged connection feature is reimplemented.

## Baseline and authority

Refresh `origin/main` and issue #10. Inspect PRs #51 through #56, their commits and checks, current
Google routes, migrations, token-vault behavior, provider mocks, frontend card, and latest hosted
verification. The accepted Google decision controls security and partial-grant behavior.

## Scope

- Audit state/PKCE/binding-cookie and replay refusal, partial and denied grants, encrypted storage,
  callback log redaction, stored-token sync, migration round trip, and default-off behavior.
- Run safe targeted tests where useful and identify whether gated verification evidence is missing.
- Prepare truthful issue, roadmap, checklist, integration-matrix, and decision-record evidence.

## Non-goals

Do not add lifecycle actions from #11, Settings lifecycle UI from #12, a live-account test, an
enablement path, new scopes, or a claim of support.

## Interfaces and data flow

This is evidence-only. Do not change routes, response types, database schema, scopes, token flow,
or browser behavior. Google remains an optional external destination initiated by the user.

## Safety and approval gates

Use mocked Google responses and synthetic values. Never reveal callback parameters or secrets.
Request per-run approval before full verification. Closing #10 requires maintainer approval after
the evidence change merges.

## Implementation steps

1. Build criterion-to-code/test/run traceability at the refreshed commit.
2. If a criterion lacks evidence, report it instead of coding beyond this prompt.
3. Make only evidence and status-document edits on a `docs/` branch.
4. Open a review-ready PR using `Part of #10`, not a closing keyword.

## Verification

Run the focused backend/frontend unit tests cited by the audit, documentation/link checks, and
`git diff --check`. List full verification as unrun unless separately approved.

## Documentation and evidence

Record PRs #51–#56 and applicable hosted runs. Say explicitly that the flow is implemented with
simulated provider responses, disabled in shipped configurations, and not supported.

## Stop conditions

Stop for a substantive unmet acceptance criterion, a security ambiguity, missing hosted evidence
that requires a gated run, or any proposal to use a live Google account.
