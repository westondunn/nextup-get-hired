# Synchronize and publish reviewed wiki summaries

> Draft only. Review and approve before creating a GitHub issue.

## User problem and intended outcome

The published wiki can lag canonical repository documents and show obsolete status. Outcome: synchronize the repository wiki drafts after canonical documents settle, then publish only with explicit maintainer approval and record the source revision.

## Current state

`docs/wiki/README.md` records that the Integrations draft is newer than the published page; other pages also predate the core-first work-program decision. Reviewed at commit `f9024aa` (`main`) on 2026-11-23.

## Scope

- Reconcile Home, Roadmap, and Integrations drafts with merged canonical sources.
- Convert links for wiki use and prepare a publication diff.
- After explicit approval, publish and record wiki revision, source commit, and date in a follow-up PR.

## Non-goals

- No publication before canonical sources merge or without explicit approval.
- No new claims, issue status, or support status originating in the wiki.

## Capabilities and data flows

Public documentation moves from the repository to the separate GitHub wiki repository.

## Dependencies and unresolved decisions

Blocked until the relevant roadmap, governance, onboarding, and integration documents settle.

## Acceptance criteria

- Draft summaries match canonical claims and links resolve.
- Publication is a separately approved action.
- Repository status records the exact wiki revision and synchronization date.

## Security, privacy, failure handling and data preservation

Publish no secrets, personal data, private security details, or unverified support claims. If publication fails, the repository drafts remain authoritative.

## Evidence expected

Draft link checks, reviewed wiki diff, opened pages after publication, and the recording PR.

## Documentation affected

`docs/wiki/` and its canonical source links.

## Contributor notes

- Suggested branch: `docs/synchronize-wiki-summaries` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: documentation and separate wiki repository.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: governance execution tracker, once created
- Actual branch and pull request: not created yet
- Verification evidence: pending
