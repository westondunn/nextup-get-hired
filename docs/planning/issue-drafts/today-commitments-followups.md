# Show Today commitments and follow-ups under the correct conditions

> Draft only. Review and approve before creating a GitHub issue.

## User problem and intended outcome

Today can hide follow-ups when they are the only populated list and never renders commitment rows even though commitments control the section's visibility. Outcome: each Today collection is rendered under its own condition with focused regression coverage.

## Current state

`TodayView.tsx` opens the section for `interviews || commitments` but renders interviews and `follow_ups`. No commitment list is rendered. Reviewed at commit `f9024aa` (`main`) on 2026-11-23.

## Scope

- Resolve the intended display for interviews, commitments, and follow-ups from the API shape.
- Make the visibility and rendered collections consistent.
- Add component tests for each list alone and in combination.

## Non-goals

- No Today redesign, backend scheduling change, or new task type.

## Capabilities and data flows

Local presentation of existing core data. No new data flow.

## Dependencies and unresolved decisions

Confirm whether commitments need a distinct panel or belong with an existing list before editing.

## Acceptance criteria

- Follow-ups display when they are the only populated collection.
- Commitments are either rendered or removed from the section contract with matching API/test evidence.
- Empty collections create no misleading heading.

## Security, privacy, failure handling and data preservation

Presentation-only change; no record mutation. Tests use synthetic records.

## Evidence expected

Focused Vitest cases plus the frontend test, typecheck, build, and format checks.

## Documentation affected

None expected unless the Today behavior is documented elsewhere.

## Contributor notes

- Suggested branch: `bugfix/today-commitments-followups` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: `frontend/src/hub/TodayView.tsx` and colocated tests.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: core public preview tracker, once created
- Actual branch and pull request: not created yet
- Verification evidence: pending
