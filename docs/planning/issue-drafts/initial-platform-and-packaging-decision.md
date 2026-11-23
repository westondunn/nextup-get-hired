# Decide the initial platform and packaging path for core setup

> Draft only. Review and approve before creating a GitHub issue.

## User problem and intended outcome

The accepted setup design cannot be implemented safely until the first claimed platform and delivery mechanism are explicit. Outcome: an accepted ADR selects the smallest initial platform/architecture and packaging path, or recommends delaying implementation.

## Current state

Verification has run on Linux with Docker, while no platform is supported and `CORE_ONBOARDING.md` deliberately leaves packaging and initial platforms open. Reviewed at commit `f9024aa` (`main`) on 2026-11-23.

## Scope

- Compare the existing launcher/Compose path with practical packaging options.
- Evaluate prerequisites, upgrades, rollback, signing/distribution, accessibility, and maintenance cost.
- Recommend one initial platform/architecture and state explicit exclusions.

## Non-goals

- No installer implementation or platform support claim.
- No weakening of loopback binding, secret files, or migration confirmation.

## Capabilities and data flows

Core installation only. Record dependency-download destinations; no job-search data is sent elsewhere.

## Dependencies and unresolved decisions

Blocked on #28 acceptance. The maintainer must accept the ADR before implementation children start.

## Acceptance criteria

- Candidates are scored against the same published criteria.
- The recommendation states update, rollback, data-location, and prerequisite behavior.
- Unsupported platforms and unknowns are explicit.

## Security, privacy, failure handling and data preservation

The selected path must retain loopback exposure, restricted secrets, guarded migrations, and recoverable local data. Research uses no personal data.

## Evidence expected

Primary-source platform/tool documentation with review dates and an accepted ADR.

## Documentation affected

New ADR, `docs/CORE_ONBOARDING.md`, roadmap, and development notes.

## Contributor notes

- Suggested branch: `docs/initial-platform-packaging-decision` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: documentation and packaging analysis.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: core public preview tracker, once created
- Blocked by: #28
- Actual branch and pull request: not created yet
- Verification evidence: pending
