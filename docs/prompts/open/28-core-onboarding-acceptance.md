---
work_id: live-28-core-onboarding-acceptance
status: live
issue: 28
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.2-sol
depends_on: live-23-interoperability-acceptance
approval_gates: maintainer-decision, issue-publication, issue-close
canonical_sources: docs/CORE_ONBOARDING.md, docs/ROADMAP.md, docs/RELEASE_CHECKLIST.md, https://github.com/westondunn/nextup-get-hired/issues/28
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Accept and decompose the core-onboarding design

## Outcome

The maintainer accepts or amends the merged design, closes #28 as a design issue, and receives a
non-overlapping child-issue map for the core-first public milestone.

## Baseline and authority

Refresh issue #28, PRs #68/#69, `CORE_ONBOARDING.md`, current launcher/UI/browser tests, and the
release checklist. Correct stale facts such as the already-fixed executable bit. The design's
explicit rule—no implementation issues before acceptance—controls.

## Scope

- Audit baseline, retry/preservation, offline core workflow, accessibility, clean-machine, and
  representative-user requirements.
- Present unresolved initial-platform/packaging choices explicitly.
- Decompose accepted work into platform/packaging decision, guided setup, in-app first run,
  offline/persistence/egress evidence, accessibility, clean-machine, and user-validation outcomes.

## Non-goals

No setup implementation, platform claim, user session, issue publication, weakening of the
migration guard, automatic reset, or integration/AI onboarding.

## Interfaces and data flow

Review the core local-only path. After dependency downloads, core workflows must operate without
external egress. Keep setup state, installation identity, guarded migration confirmation, retry,
and data retention requirements explicit; exact interfaces belong in accepted child issues.

## Safety and approval gates

Only the maintainer accepts the design and approves publishing children. Preserve loopback binding,
restricted secret files, guarded migrations, data on retry, and synthetic validation records.

## Implementation steps

1. Map #28 criteria to the merged design and current product gaps.
2. Present accept/amend options and the proposed child dependency graph.
3. Stop for the maintainer's explicit decision.
4. Record acceptance in a documentation PR; publish approved child issues only in a separate,
   explicitly invoked issue-publication step.

## Verification

Run documentation/link checks, static UI/API gap checks, and `git diff --check`. Do not run setup,
full verification, or user research merely to accept the design.

## Documentation and evidence

After acceptance, update design status, roadmap ordering, release-checklist issue references, and
the #28 evidence record. Keep targets separate from measured validation results.

## Stop conditions

Stop for missing maintainer acceptance, an implicit platform/packaging choice, overlapping children,
or a proposal that weakens migration, secret, loopback, retry, or preservation safeguards.
