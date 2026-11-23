# NextUp roadmap

This page lists the planned outcomes. P0 records the completed safety baseline. The [maintainer work program](WORK_PROGRAM.md) records execution prompts and proposed issue drafts without replacing the live issues or this roadmap. This is public planning for a pre-release project. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](../CONTRIBUTING.md)), so nothing here is an invitation to start work.

**Execution direction selected 2026-11-23 at `f9024aa`:** the next public milestone is a core-only preview with every integration and AI feature off. Google remains the first connection track, but it does not gate that milestone. Acceptance of the interoperability policy (#23) and core-onboarding design (#28) precedes publishing the proposed core children. The remaining provisional interoperability outcomes keep their existing dependencies and are not promoted into the core critical path by this decision.

**Roadmap snapshot: 2026-11-14 at `c143b87`.** The interoperability and onboarding entries for #24, #26, #27 and #28 were reconciled against `main` at `bc536d1073f799da1efd2f7ccc8dae038be0e617`, covering the documentation delivered in PRs #65–#68. Status, scope and acceptance criteria live in the linked issues; where this page and an issue disagree, the issue is right. The parent tracking issue is [#3](https://github.com/westondunn/nextup-get-hired/issues/3). There is no GitHub Project for this repository.

An outcome is checked only when its completion gate is met and the evidence is linked. A branch, an open pull request or a closed issue does not check it. Readiness gates for a public release are in the [release checklist](RELEASE_CHECKLIST.md).

Branch names below are suggestions that follow the [branching guide](BRANCHING.md). The branch actually used is recorded in the issue.

## What exists today

- Read-only Gmail and Google Calendar sync are implemented and switched off in every shipped configuration. A consent flow that stores an encrypted grant exists in the API and has been tested with simulated Google responses only ([#10](https://github.com/westondunn/nextup-get-hired/issues/10), in progress). Sync uses the stored grant when one exists. Settings has a card that saves the Google client and starts the flow; in every shipped configuration it reports that no Google account can be connected. There is no supported way to enable any of it.
- Job-listing fetching from Adzuna and from Greenhouse, Lever and Ashby boards is implemented and switched off in every shipped configuration, with no supported way to enable it.
- The API has no authentication and is published on the loopback interface only. It refuses requests to a non-local host name and cross-origin state-changing requests. Changing or running mail and calendar sync requires a local session, and so do the Google client and connection routes, except the address Google sends the browser back to. No other route does.
- The optional external classifier interface is described in [CORRESPONDENCE_SYNC.md](CORRESPONDENCE_SYNC.md) and is refused in every environment.
- There is no code for other mail or calendar providers (IMAP, SMTP, CalDAV, iCalendar), an AI provider, MCP, a workflow tool, Google Docs or first-run onboarding.
- Every integration has support status `None` in the [integration matrix](INTEGRATIONS.md).

## P0 — Tracking baseline and safety

- [x] **Outcome: the roadmap and release checklist are published**
  - Tracking: [#4](https://github.com/westondunn/nextup-get-hired/issues/4)
  - Priority and dependencies: P0; none
  - Suggested branch: `docs/4-integration-readiness-roadmap` (actual: `docs/integration-readiness-roadmap`)
  - Contributor notes: `docs/`, `README.md`; documentation only
  - Contribution availability: maintainer-only
  - Complete when: both documents are merged with every link verified, and wiki drafts are staged as unpublished
  - Evidence: merged in [#15](https://github.com/westondunn/nextup-get-hired/pull/15) as `6548863`; [hosted CI run on `main`](https://github.com/westondunn/nextup-get-hired/actions/runs/43491072504); completion record in [#4](https://github.com/westondunn/nextup-get-hired/issues/4). The Home and Roadmap wiki pages were published afterwards; see [wiki/README.md](wiki/README.md)

- [x] **Outcome: the development notes link to the branching guide and describe hosted CI accurately**
  - Tracking: [#5](https://github.com/westondunn/nextup-get-hired/issues/5)
  - Priority and dependencies: P0; none
  - Suggested branch: `docs/5-branching-adoption` (used as suggested)
  - Contributor notes: `docs/DEVELOPMENT.md`, `docs/BRANCHING.md`; no naming check or ruleset change
  - Contribution availability: maintainer-only
  - Complete when: the guide is linked and every hosted-CI statement cites a run
  - Evidence: merged in [#33](https://github.com/westondunn/nextup-get-hired/pull/33) as `ddb1022`; [hosted CI run on `main`](https://github.com/westondunn/nextup-get-hired/actions/runs/43545101394) at `314d8b8`, the first run that includes it. The development notes link the guide and cite a hosted run; branch naming is still not enforced

- [x] **Outcome: a contribution guide and issue and pull-request templates exist, with contributions still closed**
  - Tracking: [#6](https://github.com/westondunn/nextup-get-hired/issues/6)
  - Priority and dependencies: P0; follows [#4](https://github.com/westondunn/nextup-get-hired/issues/4)
  - Suggested branch: `docs/6-contribution-guide` (used as suggested)
  - Contributor notes: repository root and `.github/`; must not open contributions or duplicate the branching rules
  - Contribution availability: maintainer-only
  - Complete when: the guide and templates are merged and render correctly on GitHub
  - Evidence: merged in [#36](https://github.com/westondunn/nextup-get-hired/pull/36) as `e9628bd`; [hosted CI run on `main`](https://github.com/westondunn/nextup-get-hired/actions/runs/43650497960). On `main`, GitHub's API lists the issue template by its name and description and reports the pull-request template and the contribution guide; the record is in [#6](https://github.com/westondunn/nextup-get-hired/issues/6). Contributions remain closed, and no label was applied

- [x] **Outcome: the local session, CSRF and Host/Origin boundary is decided**
  - Tracking: [#7](https://github.com/westondunn/nextup-get-hired/issues/7)
  - Priority and dependencies: P0; none. Blocks [#8](https://github.com/westondunn/nextup-get-hired/issues/8) and [#9](https://github.com/westondunn/nextup-get-hired/issues/9)
  - Suggested branch: `docs/7-local-session-boundary-adr` (used as suggested)
  - Contributor notes: decision record under `docs/`; browser security for local services
  - Contribution availability: maintainer-only
  - Complete when: the decision record is reviewed and merged
  - Evidence: [PR #17](https://github.com/westondunn/nextup-get-hired/pull/17) proposed decision 0001. The maintainer recorded acceptance on 2026-11-13 in [PR #19](https://github.com/westondunn/nextup-get-hired/pull/19) ([`6ef8a00`](https://github.com/westondunn/nextup-get-hired/commit/6ef8a0093ee74a7cfce7e8da85e8f0b63309b483)). The [accepted CSRF decision](decisions/0001-local-session-boundary.md#layer-2--cross-origin-refusal-state-changing-requests) uses Fetch Metadata and Origin checks and supersedes the per-request token criterion in #7.

- [x] **Outcome: requests to a non-local host name and cross-origin state-changing requests are refused**
  - Tracking: [#8](https://github.com/westondunn/nextup-get-hired/issues/8)
  - Priority and dependencies: P0; blocked by [#7](https://github.com/westondunn/nextup-get-hired/issues/7)
  - Suggested branch: `feature/8-local-request-boundary` (used as suggested)
  - Contributor notes: `backend/app/main.py` and a new backend module; no frontend change; loopback-only publication does not change
  - Contribution availability: maintainer-only
  - Complete when: each refusal path and each access path is tested and the full verification passes
  - Evidence: merged in [#20](https://github.com/westondunn/nextup-get-hired/pull/20) as `baf9028`; [hosted CI run on `main`](https://github.com/westondunn/nextup-get-hired/actions/runs/43509731795), which includes the integration, browser and secret-audit checks; local probes of the development stack are recorded in the pull request

- [x] **Outcome: integration and credential routes require a local session**
  - Tracking: [#18](https://github.com/westondunn/nextup-get-hired/issues/18)
  - Priority and dependencies: P0; blocked by [#8](https://github.com/westondunn/nextup-get-hired/issues/8)
  - Suggested branch: `feature/18-local-session` (used for the first part; the second part used `feature/18-session-enforcement`)
  - Contributor notes: `scripts/oss_env.py`, the Compose overlays, `backend/app/local_session.py`, `backend/app/correspondence.py`, `frontend/src/hub/SettingsView.tsx`; sessions are stored in Redis, so there is no migration
  - Contribution availability: maintainer-only
  - Complete when: session start, expiry and refusal are tested, the secret audit passes, and the Settings prompt has accessibility coverage
  - Evidence: the setup code and session routes were merged in [#22](https://github.com/westondunn/nextup-get-hired/pull/22) as `81ac008`, and the session requirement and Settings prompt in [#31](https://github.com/westondunn/nextup-get-hired/pull/31) as `7370e9a`; [hosted CI run on `main`](https://github.com/westondunn/nextup-get-hired/actions/runs/43538353763), which includes the integration suites, the live-stack session test, the browser tests and the secret audit; local probes of the development stack are recorded in both pull requests

## P1 — Google connection (the first connection path)

This remains the first connection to be completed and validated. It is not supported yet. The interoperability direction does not replace or restart it.

- [x] **Outcome: the Google OAuth client registration, flow and token storage are decided**
  - Tracking: [#9](https://github.com/westondunn/nextup-get-hired/issues/9)
  - Priority and dependencies: P1; blocked by [#7](https://github.com/westondunn/nextup-get-hired/issues/7)
  - Suggested branch: `docs/9-google-oauth-adr` (used as suggested)
  - Contributor notes: decision record under `docs/decisions/`; must cite current official Google documentation; the registration is user-owned, the client type is Web application, client credentials are entered in Settings, and the configuration refresh token stays as a fallback
  - Contribution availability: maintainer-only
  - Complete when: the decision record is reviewed and merged
  - Evidence: [PR #46](https://github.com/westondunn/nextup-get-hired/pull/46) proposed [decision 0003](decisions/0003-google-connection.md) from Google's documentation. [Hosted CI passed at `91aa6c7`](https://github.com/westondunn/nextup-get-hired/actions/runs/43668150428). The maintainer recorded acceptance on 2026-11-14 in [PR #47](https://github.com/westondunn/nextup-get-hired/pull/47) ([`bab594e`](https://github.com/westondunn/nextup-get-hired/commit/bab594ed87a4b97af05ff92268d36edd9973ef4e)). Live-account validation is pending.

- [ ] **Outcome: a user can connect a Google account through the browser for read-only Gmail and Calendar**
  - Tracking: [#10](https://github.com/westondunn/nextup-get-hired/issues/10)
  - Priority and dependencies: P1; blocked by [#8](https://github.com/westondunn/nextup-get-hired/issues/8), [#18](https://github.com/westondunn/nextup-get-hired/issues/18) and [#9](https://github.com/westondunn/nextup-get-hired/issues/9)
  - Suggested branch: `feature/10-google-oauth-onboarding`
  - Contributor notes: `backend/app/sources/`, `backend/app/config.py`, a new migration; existing configuration refusals stay unless the decision record changes them
  - Contribution availability: maintainer-only
  - Complete when: the flow, its refusal paths and the migration round trip pass with mocked provider calls
  - Implementation evidence: [#51](https://github.com/westondunn/nextup-get-hired/pull/51) and [#52](https://github.com/westondunn/nextup-get-hired/pull/52) added encryption and the connection table. [#53](https://github.com/westondunn/nextup-get-hired/pull/53) and [#54](https://github.com/westondunn/nextup-get-hired/pull/54) added client saving, consent and callback. [#55](https://github.com/westondunn/nextup-get-hired/pull/55) connected sync to the stored grant, and [#56](https://github.com/westondunn/nextup-get-hired/pull/56) added the Settings card that starts consent. [Hosted CI passed at `4589435`](https://github.com/westondunn/nextup-get-hired/actions/runs/43777493105) with simulated Google responses. The review against #10's acceptance criteria is pending.

- [ ] **Outcome: a user can check, renew and remove a Google connection**
  - Tracking: [#11](https://github.com/westondunn/nextup-get-hired/issues/11)
  - Priority and dependencies: P1; blocked by [#10](https://github.com/westondunn/nextup-get-hired/issues/10)
  - Suggested branch: `feature/11-google-connection-lifecycle`
  - Contributor notes: `backend/app/correspondence.py`, `backend/app/correspondence_tasks.py`
  - Contribution availability: maintainer-only
  - Complete when: every connection state, including revoked and unreachable, is tested
  - Evidence: pending

- [ ] **Outcome: Settings shows the Google connection state and actions**
  - Tracking: [#12](https://github.com/westondunn/nextup-get-hired/issues/12)
  - Priority and dependencies: P1; blocked by [#11](https://github.com/westondunn/nextup-get-hired/issues/11)
  - Suggested branch: `feature/12-google-connection-settings`
  - Contributor notes: `frontend/src/hub/SettingsView.tsx`; includes accessibility coverage
  - Contribution availability: maintainer-only
  - Complete when: each state has a tested rendering and the accessibility checks pass
  - Evidence: the [Settings card delivered for #10](https://github.com/westondunn/nextup-get-hired/pull/56) shows Google as unavailable in shipped configurations. The lifecycle states, actions and accessibility checks for #12 depend on #11.

- [x] **Outcome: calendar import and display are tested across daylight-saving boundaries**
  - Tracking: [#13](https://github.com/westondunn/nextup-get-hired/issues/13)
  - Priority and dependencies: P1; none
  - Suggested branch: `test/13-calendar-dst-boundaries` (used as suggested)
  - Contributor notes: `backend/tests/test_calendar_dst.py`, `frontend/src/hub/SearchPlanView.dst.test.tsx`; synthetic fixtures only
  - Contribution availability: candidate once contributions open; maintainer-only until then
  - Complete when: UTC and America/Chicago transition cases run in the documented verification
  - Evidence: merged in [#40](https://github.com/westondunn/nextup-get-hired/pull/40) as `325cc46`; [hosted CI run on `main`](https://github.com/westondunn/nextup-get-hired/actions/runs/43654485058), which ran the new cases. The tests found two defects, tracked below; each was held in the suite as an expected failure until corrected. This outcome is that the behavior is tested, not that it is correct

- [x] **Outcome: an all-day calendar event is shown on its own date in every time zone**
  - Tracking: [#38](https://github.com/westondunn/nextup-get-hired/issues/38)
  - Priority and dependencies: not placed; found by [#13](https://github.com/westondunn/nextup-get-hired/issues/13)
  - Suggested branch: `bugfix/38-all-day-event-date` (used for the stored flag; the display change used `bugfix/38-all-day-event-display`)
  - Contributor notes: `backend/app/correspondence_tasks.py`, `frontend/src/hub/MessageCard.tsx`; the date is carried by a stored flag, added by migration `oss_0030`, the first revision after the pinned history
  - Contribution availability: maintainer-only
  - Complete when: the expected-failure cases for all-day events pass in UTC and America/Chicago and their markers are removed
  - Evidence: the stored flag merged in [#48](https://github.com/westondunn/nextup-get-hired/pull/48) as `b3ece31` and the display change in [#49](https://github.com/westondunn/nextup-get-hired/pull/49) as `c143b87`; [hosted CI run on `main`](https://github.com/westondunn/nextup-get-hired/actions/runs/43672928458), in which the frontend suite has no expected failure left and the migration ran through the guard. Events imported before the flag existed and now outside the sync window are not corrected. Tested at component level, with no browser test and no live calendar

- [x] **Outcome: a calendar event time without an offset is read in the time zone the event names**
  - Tracking: [#39](https://github.com/westondunn/nextup-get-hired/issues/39)
  - Priority and dependencies: not placed; found by [#13](https://github.com/westondunn/nextup-get-hired/issues/13)
  - Suggested branch: `bugfix/39-calendar-event-time-zone` (used as suggested)
  - Contributor notes: `backend/app/sources/google_calendar.py`; whether the provider ever returns this form is not verified
  - Contribution availability: maintainer-only
  - Complete when: the expected-failure cases pass and their marker is removed
  - Evidence: merged in [#42](https://github.com/westondunn/nextup-get-hired/pull/42) as `be66581`; [hosted CI run on `main`](https://github.com/westondunn/nextup-get-hired/actions/runs/43658531564), in which the backend suite has no expected failure left. A repeated or skipped wall-clock time follows RFC 5545, and an event whose start names an unknown zone is left out of the import. Not verified against a live calendar

- [ ] **Outcome: the Google setup is validated from a clean machine**
  - Tracking: [#14](https://github.com/westondunn/nextup-get-hired/issues/14)
  - Priority and dependencies: P1; blocked by [#10](https://github.com/westondunn/nextup-get-hired/issues/10), [#11](https://github.com/westondunn/nextup-get-hired/issues/11) and [#12](https://github.com/westondunn/nextup-get-hired/issues/12); a live-account test needs separate maintainer approval
  - Suggested branch: `docs/14-google-oauth-setup`
  - Contributor notes: setup guide under `docs/`, README status table
  - Contribution availability: maintainer-only
  - Complete when: a dated clean-machine run is recorded for each platform claimed
  - Evidence: pending

## Interoperability and onboarding

The core preview requires no enabled integration. The maintainer accepted the policy tracked in #23. The proposed core implementation issues still depend on design acceptance in #28. The other interoperability outcomes retain their existing dependencies. See the [work order](WORK_PROGRAM.md#work-order) and the open choices in [decision 0002](decisions/0002-standards-first-interoperability.md).

- [x] **Outcome: the standards-first interoperability policy is accepted**
  - Tracking: [#23](https://github.com/westondunn/nextup-get-hired/issues/23)
  - Priority and dependencies: policy acceptance precedes the proposed core implementation issues. No prerequisite.
  - Suggested branch: `docs/23-standards-first-interoperability`
  - Contributor notes: [decision 0002](decisions/0002-standards-first-interoperability.md) records the policy and the owner and review point for each deferred choice.
  - Contribution availability: maintainer-only
  - Complete when: the maintainer sets the record's status and the public documents contain none of the excluded claims
  - Evidence: [PR #29](https://github.com/westondunn/nextup-get-hired/pull/29) recorded the agreed direction. [PR #69](https://github.com/westondunn/nextup-get-hired/pull/69) reconciled the subsequent decisions and documents. The maintainer accepted the amended policy on 2026-11-23 following the [review of public claims in the repository and wiki](decisions/0002-standards-first-interoperability.md#acceptance-review).

- [ ] **Outcome: a shared read-only correspondence capability contract is defined**
  - Tracking: [#24](https://github.com/westondunn/nextup-get-hired/issues/24)
  - Priority and dependencies: provisional; follows [#23](https://github.com/westondunn/nextup-get-hired/issues/23)
  - Suggested branch: `docs/24-correspondence-capability-contract`
  - Contributor notes: a contract document under `docs/`; maps the existing Gmail adapter onto it; no code change, no renamed stored keys
  - Contribution availability: maintainer-only
  - Complete when: the maintainer accepts the merged contract with the Gmail mapping and its gaps
  - Evidence: [the proposed contract](CORRESPONDENCE_CAPABILITY.md), including the Gmail mapping and required synthetic tests, merged in [PR #65](https://github.com/westondunn/nextup-get-hired/pull/65) ([`759e53c`](https://github.com/westondunn/nextup-get-hired/commit/759e53cd3dfa930de53a2c74c307aa7bf1276cbd)). Maintainer acceptance in [#24](https://github.com/westondunn/nextup-get-hired/issues/24) and future adapter validation are pending.

- [ ] **Outcome: a second, independent email adapter has been evaluated**
  - Tracking: [#25](https://github.com/westondunn/nextup-get-hired/issues/25)
  - Priority and dependencies: provisional; blocked by [#24](https://github.com/westondunn/nextup-get-hired/issues/24)
  - Suggested branch: `docs/25-second-email-adapter-evaluation`
  - Contributor notes: bounded discovery; no provider or protocol chosen in advance; no implementation
  - Contribution availability: maintainer-only
  - Complete when: a written evaluation ends in one recommendation, or in a recommendation not to proceed
  - Evidence: pending

- [x] **Outcome: an optional AI task contract defines separate connectivity and quality checks**
  - Tracking: [#26](https://github.com/westondunn/nextup-get-hired/issues/26)
  - Priority and dependencies: provisional; follows [#23](https://github.com/westondunn/nextup-get-hired/issues/23)
  - Suggested branch: `docs/26-ai-task-contract`
  - Contributor notes: one narrow task, a classification hint for an imported message
  - Contribution availability: maintainer-only
  - Complete when: the contract names one task, its schema, consent and destination rules, and separate connectivity and quality checks
  - Evidence: [the AI task contract](AI_TASK_CONTRACT.md) merged in [PR #66](https://github.com/westondunn/nextup-get-hired/pull/66) ([`1cd5886`](https://github.com/westondunn/nextup-get-hired/commit/1cd5886e40e47b312476234af346708357ef232e)). Processor implementation, endpoint validation and measured quality remain pending.

- [x] **Outcome: a tested-compatibility policy and support matrix are maintained**
  - Tracking: [#27](https://github.com/westondunn/nextup-get-hired/issues/27)
  - Priority and dependencies: provisional; follows [#23](https://github.com/westondunn/nextup-get-hired/issues/23)
  - Suggested branch: `docs/27-compatibility-matrix`
  - Contributor notes: [INTEGRATIONS.md](INTEGRATIONS.md); implementation status and support status stay separate
  - Contribution availability: maintainer-only
  - Complete when: every integration in code has a row and no row says Tested without linked, dated evidence
  - Evidence: the [support policy and matrix](INTEGRATIONS.md#support-evidence-and-re-validation) and [release review gates](RELEASE_CHECKLIST.md#compatibility-matrix) were delivered in [PR #67](https://github.com/westondunn/nextup-get-hired/pull/67) ([`7dee028`](https://github.com/westondunn/nextup-get-hired/commit/7dee028ab6b817a0afd6ab8410c35fa52bb6d02b)). The matrix covers the implemented integrations and every row has support status None.

- [ ] **Outcome: first-run setup of the core application is guided and validated, with no integration or AI**
  - Tracking: [#28](https://github.com/westondunn/nextup-get-hired/issues/28)
  - Priority and dependencies: design acceptance follows [#23](https://github.com/westondunn/nextup-get-hired/issues/23) and precedes publication of the proposed core implementation issues.
  - Suggested branch: `docs/28-core-onboarding-design`
  - Contributor notes: design first; no packaging approach chosen in advance; migration confirmation, secret files and loopback exposure are not weakened
  - Contribution availability: maintainer-only
  - Complete when: the maintainer accepts the design in #28 and the later [core release checks](RELEASE_CHECKLIST.md#core-application) record clean-machine and representative-user results separately from their targets.
  - Evidence: [the proposed first-run design](CORE_ONBOARDING.md) merged in [PR #68](https://github.com/westondunn/nextup-get-hired/pull/68) ([`bc536d1`](https://github.com/westondunn/nextup-get-hired/commit/bc536d1073f799da1efd2f7ccc8dae038be0e617)). Maintainer acceptance in [#28](https://github.com/westondunn/nextup-get-hired/issues/28), implementation, clean-machine runs and representative-user sessions remain pending.

## P2 — Optional workflow access (planned, not yet tracked)

No issues have been filed.

- A narrow, authenticated interface through which another tool can work with NextUp, with NextUp remaining the authoritative record. A versioned API is one possible form; nothing is decided.
- Workflow tools such as n8n are optional clients of that interface, never a dependency of the core. Any example workflow is sanitized and versioned.
- Read-only import kept separate from any mailbox change. No automatic sending and no automatic job applications.
- The external classifier contract in [CORRESPONDENCE_SYNC.md](CORRESPONDENCE_SYNC.md) is preserved: hints never override NextUp's detection or existing links.

## P3 — Optional AI assistance and operations tooling (planned)

The first [AI task contract](AI_TASK_CONTRACT.md) was delivered for [#26](https://github.com/westondunn/nextup-get-hired/issues/26). The implementation and evaluation work below is untracked.

- A processor adapter only where a defined task needs one. Local inference is optional, and cloud processing is an explicit opt-in with the destination shown.
- A separate evaluation of AI quality against labelled synthetic fixtures and a rule-only baseline, so that working connectivity is not mistaken for demonstrated quality.
- Documented boundaries for optional operations tools before any connector is built. None of them becomes a dependency of the core.

## Deferred and discovery work (not tracked)

Recorded so that it is not mistaken for planned or supported work. None of these has an issue, and none is scheduled.

- Sending mail (SMTP submission or a provider API).
- Calendar synchronization beyond the existing read-only Google adapter, including CalDAV and iCalendar file import or export.
- Additional mail or calendar providers beyond the evaluation in [#25](https://github.com/westondunn/nextup-get-hired/issues/25).
- Assistant access through MCP.
- A versioned public API.
- Advanced automation.

## Separate, approval-gated work

Automated branch-name checking and any change to the `main` ruleset are described as proposals in the [branching guide](BRANCHING.md). They are not scheduled here and need maintainer approval before they start.
