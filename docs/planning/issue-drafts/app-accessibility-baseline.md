# Establish an application-wide accessibility baseline

> Draft only. Review and approve before creating a GitHub issue.

## User problem and intended outcome

Core dialogs, drawers, empty-state actions, and icon controls do not consistently expose names, dialog semantics, focus containment/restoration, or Escape behavior. Outcome: the core workflow meets a documented keyboard and assistive-technology baseline before representative-user validation.

## Current state

Accessibility tests exist for selected components, while the broader shell and feature modals have no shared interaction contract. Issues #12 and #28 cover narrower surfaces. Reviewed at commit `f9024aa` (`main`) on 2026-11-23.

## Scope

- Inventory core dialogs, drawers, menus, status messages, and icon-only controls.
- Define and implement shared dialog/focus behavior where practical.
- Add automated and manual keyboard/screen-reader coverage for core workflows.

## Non-goals

- No visual redesign or claim of formal conformance certification.
- No duplicate of Google-specific #12 acceptance criteria.

## Capabilities and data flows

UI interaction only. No new external data flow.

## Dependencies and unresolved decisions

Coordinate with in-app first run. Visual and assistive-technology validation requires an interactive environment.

## Acceptance criteria

- Interactive controls have accessible names and visible focus.
- Modal focus enters, stays, closes with Escape where appropriate, and returns to the opener.
- Errors and async status changes are announced without duplicate noise.

## Security, privacy, failure handling and data preservation

Tests use synthetic content. Accessibility repairs must not relax URL safety, session boundaries, or data preservation.

## Evidence expected

Component tests, browser keyboard coverage, and a dated manual screen-reader/zoom/reflow record.

## Documentation affected

Core onboarding validation and release checklist evidence.

## Contributor notes

- Suggested branch: `bugfix/core-accessibility-baseline` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: frontend shell, core views, shared tests.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: core public preview tracker, once created
- Related: #12 and #28
- Actual branch and pull request: not created yet
- Verification evidence: pending
