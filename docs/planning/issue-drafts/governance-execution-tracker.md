# Governance and execution-program tracking

> Draft only. Review and approve before creating a GitHub issue.

## User problem and intended outcome

Maintainer workflow, live repository rules, and the ordered product work are recorded in several places and can drift independently. Outcome: one tracking issue coordinates the work program and governance corrections without becoming a second source of acceptance criteria.

## Current state

`docs/ROADMAP.md` and live issues hold product status, while the proposed `docs/WORK_PROGRAM.md` will index executable prompts. Live repository rules have changed since parts of the branching documentation were inspected. Reviewed at commit `f9024aa` (`main`) on 2026-11-23.

## Scope

- Track publication and maintenance of the work program and prompt pack.
- Link the focused governance, workflow-lint, and issue-publication children.
- Require each child to update its canonical source rather than copying status here.

## Non-goals

- No product implementation, ruleset change, merge, or issue creation in this tracker.
- No replacement for GitHub issues, ADRs, the roadmap, or the release checklist.

## Capabilities and data flows

None. Repository metadata and public GitHub configuration are read; no user job-search data leaves NextUp.

## Dependencies and unresolved decisions

Depends on maintainer approval of the work-program documentation. Child issues are created only after their drafts are approved.

## Acceptance criteria

- The work program links every live prompt and approved draft.
- Each child has one reviewable outcome and an explicit approval boundary.
- Closed or withdrawn children are reconciled without rewriting their evidence history.
- The tracker closes when the prompt pack is adopted and the initial live-rules and workflow-lint
  children are completed or explicitly deferred; routine prompt maintenance continues through
  ordinary documentation pull requests rather than a permanent meta-issue.

## Security, privacy, failure handling and data preservation

Do not include credentials, private security findings, personal data, or secret repository settings. A failed update leaves canonical documents and live issues unchanged.

## Evidence expected

Link and structure validation, the review-ready documentation pull request, and links to each approved child.

## Documentation affected

`docs/WORK_PROGRAM.md`, `docs/prompts/`, and `docs/planning/issue-drafts/`.

## Contributor notes

- Suggested branch: `docs/governance-execution-tracker` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: documentation only.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: none
- Actual branch and pull request: not created yet
- Verification evidence: pending
