---
work_id: proposed-guarded-google-enablement
status: proposed
issue: pending
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.2-sol
depends_on: live-10-google-connect-evidence,live-11-google-connection-lifecycle
approval_gates: issue-publication,full-verification,live-google-account
canonical_sources: backend/app/config.py,scripts/oss_env.py,docs/decisions/0003-google-connection.md,docs/planning/issue-drafts/guarded-google-enablement.md
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Add guarded Google enablement

## Outcome

Provide one explicit, local, off-by-default way to enable selected Google read capabilities for controlled validation.

## Baseline and authority

Stop unless a live issue exists and #10/#11 prerequisites are satisfied. Re-read configuration, launcher, Compose, session, vault, and provider chokepoints.

## Scope

Implement the accepted opt-in, independent capability flags, rendered-config refusals, secret scoping, and tests.

## Non-goals

No default enablement, staging support, live-account use, new scopes, or support claim.

## Interfaces and data flow

Document exact configuration inputs and Gmail/Calendar outbound destinations; no request occurs while disabled.

## Safety and approval gates

Preserve loopback, local session, file secrets, value-free errors, and `require_live_requests`. Full verification and live accounts require separate approval.

## Implementation steps

Lock refusal/enablement contracts in tests, implement narrowly, update docs/matrix without raising support status, and open a PR.

## Verification

Run backend/config/script tests, lint/format checks, and guarded verification only if approved; provider calls remain mocked.

## Documentation and evidence

Separate implemented/available/tested status and record no support evidence from mocked calls.

## Stop conditions

Stop if ambient configuration can enable requests, secrets broaden to more services, or live Google access is requested without approval.
