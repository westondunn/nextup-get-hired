# decide safe enablement and support evidence for existing job sources

> Draft only. Do not publish without explicit maintainer approval.

## User problem and intended outcome

Implemented job-source adapters are unusable in shipped configurations and have no support status.
Outcome: an evaluation recommends an explicit, off-by-default enablement and validation sequence
for Adzuna, Greenhouse, Lever, and Ashby, or recommends keeping individual sources disabled.

## Current state

All four adapters exist behind `NEXTUP_LIVE_JOB_FETCH_ENABLED`; the launcher refuses enabling it.
Automated tests use fixtures or simulated responses and no live validation is recorded. Reviewed at
commit `f9024aa` (`main`) on 2026-11-23.

## Scope

Inventory shared and provider-specific switches, settings UX, credentials, request bounds, quotas,
pagination/incomplete-result behavior, failure states, disconnect, controlled validation accounts,
and the evidence required for Experimental or Tested status per provider.

## Non-goals

No live request, implementation, support claim, scraping, automatic application, or bundled
credential in this issue.

## Capabilities and data flows

Job listings: fetch. Record the exact search/profile fields and board tokens each provider receives.

## Dependencies and unresolved decisions

Core public preview does not require a source. Decide whether enablement is provider-specific and
which controlled provider should be validated first.

## Acceptance criteria

- Each provider is evaluated separately even where code is shared.
- The recommendation preserves off-by-default behavior and bounded requests.
- Partial pages, provider changes, quotas, invalid credentials, and preservation are covered.
- Implementation and validation issues are filed only after acceptance.

## Security, privacy, failure handling and data preservation

No profile or secret appears in logs. Provider failure preserves saved jobs, ratings, user edits,
and manual workflows.

## Evidence expected

Code/configuration audit and current primary provider documentation; no personal or live account.

## Documentation affected

Evaluation report, integrations matrix, roadmap, and later provider profiles.

## Contributor notes

- Suggested branch: `docs/job-source-enablement-evaluation` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: sources, configuration, Settings, integration documentation.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: #3.
- Actual branch and pull request: not created yet.
- Verification evidence: pending.
