# Core-only public preview readiness

> Draft only. Review and approve before creating a GitHub issue.

## User problem and intended outcome

NextUp cannot yet be followed from a clean machine into a usable core workspace by a non-developer. Outcome: coordinate the first public preview around guided local setup and validated core workflows with every integration and AI feature off.

## Current state

The core application is implemented and tested, and `docs/CORE_ONBOARDING.md` proposes the path. Installation, first-run UX, clean-machine evidence, and representative-user evidence remain incomplete. Reviewed at commit `f9024aa` (`main`) on 2026-11-23.

## Scope

- Track the platform decision, guided setup, in-app first run, accessibility baseline, visible core-workflow evidence, clean-machine runs, and representative-user validation.
- Keep Google and other optional connections outside the preview gate.

## Non-goals

- No claim of production readiness or support without dated evidence.
- No provider credential, integration, AI processor, automatic application, or outbound message.

## Capabilities and data flows

Core local workflows only. After dependency downloads, job-search records remain on the machine and unexpected external egress fails validation.

## Dependencies and unresolved decisions

Blocked on acceptance of issues #23 and #28. The initial platform and packaging approach are decided in a child ADR before setup implementation.

## Acceptance criteria

- Each child has linked evidence and preserves retryable local state.
- A clean user can complete the six workflows defined in `CORE_ONBOARDING.md` after reload and restart.
- Public claims name only platforms and behavior actually validated.

## Security, privacy, failure handling and data preservation

Keep ports on loopback, secrets in restricted files, migrations guarded, and all fixtures synthetic. Failed or cancelled setup preserves configuration, volumes, and user records.

## Evidence expected

Child PRs and test runs, dated clean-machine records, redacted representative-user records, and a final release-checklist reconciliation.

## Documentation affected

`docs/ROADMAP.md`, `docs/CORE_ONBOARDING.md`, `docs/RELEASE_CHECKLIST.md`, and README status.

## Contributor notes

- Suggested branch: `docs/core-public-preview-tracker` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: cross-project tracker; children own implementation.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: none
- Related: #23 and #28
- Actual branch and pull request: not created yet
- Verification evidence: pending
