# Validate guided setup with representative users

> Draft only. Review and approve before creating a GitHub issue.

## User problem and intended outcome

Automated checks cannot show whether people unfamiliar with developer tooling can understand setup and recover from interruptions. Outcome: conduct and record the representative-user sessions defined by the accepted onboarding design before making ease-of-use claims.

## Current state

`CORE_ONBOARDING.md` proposes at least five sessions and defines privacy-safe evidence fields; none are recorded. Reviewed at commit `f9024aa` (`main`) on 2026-11-23.

## Scope

- Finalize a synthetic scenario, consent-safe observation protocol, and assistance rules.
- Run sessions across each proposed platform, including one handled interruption.
- Synthesize completion, time, confusion, assistance, accessibility observations, and blockers.

## Non-goals

- No collection of résumés, real job-search details, account credentials, or claims based only on the target number.
- No model substitutes for human participants.

## Capabilities and data flows

Core local workflow. Redacted session observations are stored in repository evidence; no participant personal data is required.

## Dependencies and unresolved decisions

Blocked by clean-machine success and the accessibility baseline. The maintainer selects participants and approves the protocol.

## Acceptance criteria

- At least the accepted minimum number of sessions (currently proposed as five) is completed, with
  every claimed platform represented.
- Sessions cover every claimed platform and the six core workflows.
- Assistance and failures are recorded separately from successful completion.
- Blocking findings are resolved and affected steps repeated before a claim is made.

## Security, privacy, failure handling and data preservation

Use participant codes and synthetic data. Omit recordings and identifying details unless separately approved and governed.

## Evidence expected

Approved protocol, redacted per-session records, synthesis, follow-up issue links, and final release-evidence review.

## Documentation affected

Core onboarding evidence, release checklist, and public setup claims.

## Contributor notes

- Suggested branch: `docs/core-representative-user-validation` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: research protocol and evidence documentation.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: core public preview tracker, once created
- Actual branch and pull request: not created yet
- Verification evidence: pending
