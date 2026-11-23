---
work_id: live-14-google-clean-machine-validation
status: live
issue: 14
primary_model: gpt-6.1-terra
reasoning_effort: ultra
validation_model: gpt-6.2-astra
depends_on: live-10-google-connect-evidence,live-11-google-connection-lifecycle,live-12-google-settings-lifecycle,proposed-guarded-google-enablement
approval_gates: live-google-account, clean-machine-run, full-verification, documentation-publication
canonical_sources: docs/decisions/0003-google-connection.md, docs/INTEGRATIONS.md, docs/RELEASE_CHECKLIST.md, https://github.com/westondunn/nextup-get-hired/issues/14
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Validate Google setup from a clean machine

## Outcome

An explicitly approved test follows the written Google setup and rollback path from scratch on each
claimed platform, producing redacted evidence that supports only the configurations exercised.

## Baseline and authority

Refresh issue #14 and confirm #10, #11, #12, guarded enablement, setup documentation, and the target
platform are complete. Confirm explicit approval naming the dedicated test account and this run.

## Scope

- Review the setup/rollback guide for completeness before execution.
- Exercise connect, capability grant, read-only sync, status/test, reauthorize, disconnect,
  revocation/failure recovery, restart, and rollback on a pristine machine or VM.
- Record platform, architecture, commit, runtime versions, exact capabilities, outcomes, and
  redacted evidence.

## Non-goals

No personal account, unsupported platform inference, write scope, production-readiness claim,
provider expansion, or code repair hidden inside the validation record.

## Interfaces and data flow

The approved test sends OAuth requests and selected read-only Gmail/Calendar requests to Google.
Record destinations and permissions, never message content, account address, tokens, or secrets.

## Safety and approval gates

This prompt is blocked without separate live-account, clean-machine, and full-verification approval.
Use a dedicated test account containing synthetic data. Terra may operate the UI only within the
approved environment. Stop on unexpected scope, egress, logging, or destructive behavior.

## Implementation steps

1. Produce a preflight record and receive all named approvals.
2. Run the documented path verbatim, recording deviations as failures.
3. File implementation defects separately; do not patch during the evidence run.
4. Have Astra review the redacted record against the support policy.
5. Open a documentation PR narrowing claims to evidence and stop before publication/merge.

## Verification

Run the approved manual matrix and, only with per-run opt-in, the disposable automated verification
at the same commit. Verify rollback, retained local data, redacted artifacts, and no write actions.

## Documentation and evidence

Update the integration profile, setup guide, development notes, release checklist, and README only
to the status justified by the record. Wiki publication remains a separate approval.

## Stop conditions

Stop if any approval is absent, the account is not dedicated/synthetic, a requested scope is broader
than documented, a secret or personal datum could enter evidence, or a platform step is ambiguous.
