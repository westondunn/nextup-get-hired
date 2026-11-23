---
work_id: live-11-google-connection-lifecycle
status: live
issue: 11
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.2-sol
depends_on: live-10-google-connect-evidence
approval_gates: full-verification, schema-decision
canonical_sources: docs/decisions/0003-google-connection.md, backend/app/google_connection.py, backend/app/google_credentials.py, https://github.com/westondunn/nextup-get-hired/issues/11
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Implement the Google connection lifecycle API

## Outcome

A local user can inspect capabilities, test the stored connection, reauthorize it, and disconnect;
local deletion always succeeds even if Google revocation cannot be confirmed.

## Baseline and authority

Refresh `origin/main`, issue #11, decision 0003, and the completed #10 foundation. Inventory the
existing connection response, row-locking token refresh, revoke helper, sync statuses, and session
requirements before choosing the smallest compatible interface.

## Scope

- Rebaseline #11's state and error contract against current code before implementation.
- Add lifecycle status/test/disconnect behavior, bounded provider calls, revoked-token mapping,
  reauthorization state, concurrent-refresh safety, and best-effort revocation.
- Preserve imported records, links, detection, and user edits on disconnect and failure.

## Non-goals

No Settings implementation, live-account validation, new scopes, write access, remote auth,
support claim, or broad correspondence-adapter refactor.

## Interfaces and data flow

Record route methods, response fields, state enum, fixed error categories, and retry semantics in
the issue or an accepted contract before coding. Status returns no token material. Test and revoke
contact only Google's documented endpoints; disconnect removes local credential material under the
connection row lock regardless of revocation outcome.

## Safety and approval gates

Every new route except the OAuth callback requires the local session. Keep provider values and
secrets out of logs/errors. A schema change needs an accepted design and the next guarded
`oss_NNNN` migration; never modify pinned history. Full verification needs per-run approval.

## Implementation steps

1. Amend the issue/contract and stop for review if the wire contract remains ambiguous.
2. Implement backend lifecycle behavior and mocked provider tests in bounded commits.
3. Update integration/profile troubleshooting text without claiming enablement or support.
4. Open a review-ready feature PR and stop before approval or merge.

## Verification

Cover connected, partial grant, revoked, unreadable, outage, quota, failed revocation, concurrent
refresh, and preservation cases with synthetic tests. Run backend unit/lint/format checks; request
approval before the disposable verification suite.

## Documentation and evidence

Update the issue baseline, decision implementation notes, integration matrix, and release gates as
appropriate. Separate mocked evidence from any future live validation.

## Stop conditions

Stop for unresolved schema/wire choices, an unsafe revocation race, a need for broader Google
permissions, a live account, or data-loss behavior not already accepted.
