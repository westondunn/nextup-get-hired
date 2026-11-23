# evaluate frontend navigation, loading, and view boundaries

> Draft only. Do not publish without explicit maintainer approval.

## User problem and intended outcome

Users need stable navigation and maintainers need reviewable view modules without assuming a
framework migration is necessary. Outcome: a measured evaluation recommends bounded follow-up
work for URLs/history, loading performance, and oversized or orphaned views.

## Current state

`NextupHub.tsx` keeps navigation in component state rather than stable URLs. Several view files
exceed 800 lines, the production bundle has previously crossed the Vite warning threshold, and
`ProfileView`/`SystemView` are not rendered by the current shell. Reviewed at commit `f9024aa`
(`main`) on 2026-11-23.

## Scope

Measure current build output and navigation behavior, inventory view ownership and dead entry
points, compare minimal routing/code-splitting options, and recommend ordered, separately
reviewable implementation issues.

## Non-goals

No implementation, visual redesign, framework rewrite, or deletion based only on an unused import
search.

## Capabilities and data flows

Core browser interface. No new external destination or stored data.

## Dependencies and unresolved decisions

Coordinate stable first-run URLs with the accepted onboarding design. Verify whether orphan views
have intended future ownership before recommending removal.

## Acceptance criteria

- The report records reproducible navigation and build measurements.
- It recommends one URL/history approach and a bounded split/removal sequence.
- Accessibility, refresh/deep-link behavior, and test migration are included.
- Follow-up issues are filed only after the recommendation is accepted.

## Security, privacy, failure handling and data preservation

Preserve loopback routing and the Google callback result flow. Do not place secrets or application
data in URLs, browser storage, or build evidence.

## Evidence expected

Static inventory, production-build measurements, and synthetic browser probes.

## Documentation affected

An evaluation document and, after acceptance, the roadmap/work program.

## Contributor notes

- Suggested branch: `docs/frontend-architecture-evaluation` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: frontend shell, build configuration, documentation.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: proposed core public preview tracker.
- Actual branch and pull request: not created yet.
- Verification evidence: pending.
