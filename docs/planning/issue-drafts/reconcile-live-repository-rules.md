# Reconcile governance documentation with live repository rules

> Draft only. Review and approve before creating a GitHub issue.

## User problem and intended outcome

A maintainer following the checked-in guidance can be told that no status check is required even though a live `maintainer-approval` gate now exists. Outcome: the repository documents accurately describe the live branch and tag rules without changing them.

## Current state

The repository has active `Maintainer approval gate`, `Protect all branches`, `Protect main`, and `Protect tags` rulesets, plus `.github/workflows/maintainer-approval.yml`. `docs/DEVELOPMENT.md`, `CONTRIBUTING.md`, and parts of `docs/BRANCHING.md` predate that state. Reviewed at commit `f9024aa` (`main`) on 2026-11-23.

## Scope

- Read the effective live rulesets and checked-in approval workflow.
- Correct governance, branching, development, and release-evidence statements.
- Record the inspection date and distinguish live settings from versioned files.

## Non-goals

- No ruleset, permission, workflow, or merge-policy mutation.
- No claim that ordinary CI is required unless the effective rules say so.

## Capabilities and data flows

Read-only GitHub repository metadata. No NextUp application data is involved.

## Dependencies and unresolved decisions

Requires read access to the repository ruleset API. Any desired policy change must be a separate approval-gated issue.

## Acceptance criteria

- Every statement about required checks, bypass, deletion, force-push, PR, and tag behavior matches the live effective rules.
- The maintainer-approval workflow and its human gate are documented without implying that agents can run it.
- Historical evidence remains dated rather than silently rewritten as current.

## Security, privacy, failure handling and data preservation

Record only public or maintainer-approved configuration facts. Do not expose tokens or private security details. If the live state cannot be read, retain the old text and record the uncertainty.

## Evidence expected

Read-only API output summarized without secrets, document link checks, and a review-ready PR.

## Documentation affected

`docs/BRANCHING.md`, `docs/DEVELOPMENT.md`, `CONTRIBUTING.md`, and relevant roadmap/checklist evidence.

## Contributor notes

- Suggested branch: `docs/reconcile-live-repository-rules` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: governance documentation.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: governance execution tracker, once created
- Actual branch and pull request: not created yet
- Verification evidence: pending
