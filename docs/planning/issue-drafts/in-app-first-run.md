# Implement the in-application core first-run path

> Draft only. Review and approve before creating a GitHub issue.

## User problem and intended outcome

An empty workspace does not lead a new user through a useful first action, and Search Plan cannot create its required campaign in the UI. Outcome: a user can begin every core workflow without seed JSON or provider setup.

## Current state

Manual jobs, contacts, résumés, and profile editing exist, but Today and Applications lack a direct application action, campaign creation is not exposed, and empty states are inconsistent. Reviewed at commit `f9024aa` (`main`) on 2026-11-23.

## Scope

- Add direct application and Job Board paths from Today.
- Add campaign creation so Search Plan works from an empty database.
- Offer optional, skippable profile setup and actionable empty states.
- Prevent first-run prompts from recurring after completion or dismissal.

## Non-goals

- No integration, AI, automatic application, provider account, or redesign of established populated workflows.

## Capabilities and data flows

Core local application, task, contact, résumé, job, and profile records. Nothing leaves NextUp.

## Dependencies and unresolved decisions

Blocked by #28 acceptance. Coordinate semantics with the core E2E evidence issue and accessibility baseline.

## Acceptance criteria

- All six `CORE_ONBOARDING.md` workflows have a visible starting action from an empty workspace.
- Profile setup can be skipped and resumed.
- Returning users are not interrupted, and records persist across reload.

## Security, privacy, failure handling and data preservation

Use existing APIs and safe rendering. Failed creates retain entered values where safe and never overwrite existing records.

## Evidence expected

Component tests, keyboard/accessibility coverage, and Playwright happy/failure paths with synthetic records.

## Documentation affected

Core onboarding design, user setup guide, roadmap, and release checklist evidence.

## Contributor notes

- Suggested branch: `feature/in-app-core-first-run` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: `frontend/src/hub/`, related API modules and tests.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: core public preview tracker, once created
- Blocked by: #28
- Actual branch and pull request: not created yet
- Verification evidence: pending
