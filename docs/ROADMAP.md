# NextUp roadmap

This page lists the planned outcomes. P0 and P1 are in order; the section added after them is not yet placed. It is public planning for a pre-release project. Outside contributions are not being accepted yet (see the [README](../README.md#development-and-contributions)), so nothing here is an invitation to start work.

**Snapshot date: 2026-11-13, last reconciled at commit `314d8b8`.** Status, scope and acceptance criteria live in the linked issues; where this page and an issue disagree, the issue is right. The parent tracking issue is [#3](https://github.com/westondunn/nextup-get-hired/issues/3). There is no GitHub Project for this repository.

An outcome is checked only when its completion gate is met and the evidence is linked. A branch, an open pull request or a closed issue does not check it. Readiness gates for a public release are in the [release checklist](RELEASE_CHECKLIST.md).

Branch names below are suggestions that follow the [branching guide](BRANCHING.md). The branch actually used is recorded in the issue.

## What exists today

- Read-only Gmail and Google Calendar sync are implemented and switched off in every shipped configuration. There is no consent flow, no stored token and no supported way to enable them.
- The API has no authentication and is published on the loopback interface only. It refuses requests to a non-local host name and cross-origin state-changing requests. Changing or running mail and calendar sync requires a local session; no other route does.
- The optional external classifier interface is described in [CORRESPONDENCE_SYNC.md](CORRESPONDENCE_SYNC.md) and is refused in every environment.
- There is no code for other mail or calendar providers (IMAP, SMTP, CalDAV, iCalendar), an AI provider, MCP, a workflow tool, Google Docs or first-run onboarding.
- Nothing has a support status. [INTEGRATIONS.md](INTEGRATIONS.md) records each integration's implementation and support status separately.

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

- [ ] **Outcome: a contribution guide and issue and pull-request templates exist, with contributions still closed**
  - Tracking: [#6](https://github.com/westondunn/nextup-get-hired/issues/6)
  - Priority and dependencies: P0; follows [#4](https://github.com/westondunn/nextup-get-hired/issues/4)
  - Suggested branch: `docs/6-contribution-guide`
  - Contributor notes: repository root and `.github/`; must not open contributions or duplicate the branching rules
  - Contribution availability: maintainer-only
  - Complete when: the guide and templates are merged and render correctly on GitHub
  - Evidence: pending

- [x] **Outcome: the local session, CSRF and Host/Origin boundary is decided**
  - Tracking: [#7](https://github.com/westondunn/nextup-get-hired/issues/7)
  - Priority and dependencies: P0; none. Blocks [#8](https://github.com/westondunn/nextup-get-hired/issues/8) and [#9](https://github.com/westondunn/nextup-get-hired/issues/9)
  - Suggested branch: `docs/7-local-session-boundary-adr` (used as suggested)
  - Contributor notes: decision record under `docs/`; browser security for local services
  - Contribution availability: maintainer-only
  - Complete when: the decision record is reviewed and merged
  - Evidence: [decisions/0001-local-session-boundary.md](decisions/0001-local-session-boundary.md), merged in [#17](https://github.com/westondunn/nextup-get-hired/pull/17) as `6da6061` and accepted by the maintainer on 2026-11-13

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

- [ ] **Outcome: the Google OAuth client registration, flow and token storage are decided**
  - Tracking: [#9](https://github.com/westondunn/nextup-get-hired/issues/9)
  - Priority and dependencies: P1; blocked by [#7](https://github.com/westondunn/nextup-get-hired/issues/7)
  - Suggested branch: `docs/9-google-oauth-adr`
  - Contributor notes: decision record under `docs/decisions/`; must cite current official Google documentation; includes who owns the client registration (bring-your-own is the working assumption, a project-managed registration is the alternative)
  - Contribution availability: maintainer-only
  - Complete when: the decision record is reviewed and merged
  - Evidence: pending

- [ ] **Outcome: a user can connect a Google account through the browser for read-only Gmail and Calendar**
  - Tracking: [#10](https://github.com/westondunn/nextup-get-hired/issues/10)
  - Priority and dependencies: P1; blocked by [#8](https://github.com/westondunn/nextup-get-hired/issues/8), [#18](https://github.com/westondunn/nextup-get-hired/issues/18) and [#9](https://github.com/westondunn/nextup-get-hired/issues/9)
  - Suggested branch: `feature/10-google-oauth-onboarding`
  - Contributor notes: `backend/app/sources/`, `backend/app/config.py`, a new migration; existing configuration refusals stay unless the decision record changes them
  - Contribution availability: maintainer-only
  - Complete when: the flow, its refusal paths and the migration round trip pass with mocked provider calls
  - Evidence: pending

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
  - Evidence: pending

- [ ] **Outcome: calendar import and display are tested across daylight-saving boundaries**
  - Tracking: [#13](https://github.com/westondunn/nextup-get-hired/issues/13)
  - Priority and dependencies: P1; none
  - Suggested branch: `test/13-calendar-dst-boundaries`
  - Contributor notes: `backend/tests/test_google_calendar.py`, `frontend/src/hub/SearchPlanView.test.tsx`; synthetic fixtures only
  - Contribution availability: candidate once contributions open; maintainer-only until then
  - Complete when: UTC and America/Chicago transition cases run in the documented verification
  - Evidence: pending

- [ ] **Outcome: the Google setup is validated from a clean machine**
  - Tracking: [#14](https://github.com/westondunn/nextup-get-hired/issues/14)
  - Priority and dependencies: P1; blocked by [#10](https://github.com/westondunn/nextup-get-hired/issues/10), [#11](https://github.com/westondunn/nextup-get-hired/issues/11) and [#12](https://github.com/westondunn/nextup-get-hired/issues/12); a live-account test needs separate maintainer approval
  - Suggested branch: `docs/14-google-oauth-setup`
  - Contributor notes: setup guide under `docs/`, README status table
  - Contribution availability: maintainer-only
  - Complete when: a dated clean-machine run is recorded for each platform claimed
  - Evidence: pending

## Interoperability and onboarding (priority provisional)

These outcomes were added on 2026-11-13 to carry the direction in [decision 0002](decisions/0002-standards-first-interoperability.md). They have no agreed position relative to P0–P3, and nothing in P0 or P1 has been moved to make room for them. Every protocol, provider and packaging choice they mention is undecided.

- [ ] **Outcome: the standards-first interoperability policy is accepted**
  - Tracking: [#23](https://github.com/westondunn/nextup-get-hired/issues/23)
  - Priority and dependencies: provisional; none
  - Suggested branch: `docs/23-standards-first-interoperability`
  - Contributor notes: `docs/decisions/0002-standards-first-interoperability.md`; the direction is agreed, the technical choices are proposals
  - Contribution availability: maintainer-only
  - Complete when: the maintainer sets the record's status and the public documents contain none of the excluded claims
  - Evidence: pending

- [ ] **Outcome: a shared read-only correspondence capability contract is defined**
  - Tracking: [#24](https://github.com/westondunn/nextup-get-hired/issues/24)
  - Priority and dependencies: provisional; follows [#23](https://github.com/westondunn/nextup-get-hired/issues/23)
  - Suggested branch: `docs/24-correspondence-capability-contract`
  - Contributor notes: a contract document under `docs/`; maps the existing Gmail adapter onto it; no code change, no renamed stored keys
  - Contribution availability: maintainer-only
  - Complete when: the contract is reviewed and merged with the Gmail mapping and its gaps
  - Evidence: pending

- [ ] **Outcome: a second, independent email adapter has been evaluated**
  - Tracking: [#25](https://github.com/westondunn/nextup-get-hired/issues/25)
  - Priority and dependencies: provisional; blocked by [#24](https://github.com/westondunn/nextup-get-hired/issues/24)
  - Suggested branch: `docs/25-second-email-adapter-evaluation`
  - Contributor notes: bounded discovery; no provider or protocol chosen in advance; no implementation
  - Contribution availability: maintainer-only
  - Complete when: a written evaluation ends in one recommendation, or in a recommendation not to proceed
  - Evidence: pending

- [ ] **Outcome: an optional AI task contract is defined, with connectivity and quality evaluated separately**
  - Tracking: [#26](https://github.com/westondunn/nextup-get-hired/issues/26)
  - Priority and dependencies: provisional; follows [#23](https://github.com/westondunn/nextup-get-hired/issues/23)
  - Suggested branch: `docs/26-ai-task-contract`
  - Contributor notes: one narrow task, proposed as a classification hint for an imported message; no provider adapter and no general agent
  - Contribution availability: maintainer-only
  - Complete when: the contract names one task, its schema, consent and destination rules, and separate connectivity and quality checks
  - Evidence: pending

- [ ] **Outcome: a tested-compatibility policy and support matrix are maintained**
  - Tracking: [#27](https://github.com/westondunn/nextup-get-hired/issues/27)
  - Priority and dependencies: provisional; follows [#23](https://github.com/westondunn/nextup-get-hired/issues/23)
  - Suggested branch: `docs/27-compatibility-matrix`
  - Contributor notes: [INTEGRATIONS.md](INTEGRATIONS.md); implementation status and support status stay separate
  - Contribution availability: maintainer-only
  - Complete when: every integration in code has a row and no row says Tested without linked, dated evidence
  - Evidence: pending

- [ ] **Outcome: first-run setup of the core application is guided and validated, with no integration or AI**
  - Tracking: [#28](https://github.com/westondunn/nextup-get-hired/issues/28)
  - Priority and dependencies: provisional; follows [#23](https://github.com/westondunn/nextup-get-hired/issues/23)
  - Suggested branch: `docs/28-core-onboarding-design`
  - Contributor notes: design first; no packaging approach chosen in advance; migration confirmation, secret files and loopback exposure are not weakened
  - Contribution availability: maintainer-only
  - Complete when: the design is accepted, and clean-machine and representative-user validation are recorded separately from their targets
  - Evidence: pending

## P2 — Optional workflow access (planned, not yet tracked)

No issues have been filed.

- A narrow, authenticated interface through which another tool can work with NextUp, with NextUp remaining the authoritative record. A versioned API is one possible form; nothing is decided.
- Workflow tools such as n8n are optional clients of that interface, never a dependency of the core. Any example workflow is sanitized and versioned.
- Read-only import kept separate from any mailbox change. No automatic sending and no automatic job applications.
- The external classifier contract in [CORRESPONDENCE_SYNC.md](CORRESPONDENCE_SYNC.md) is preserved: hints never override NextUp's detection or existing links.

## P3 — Optional AI assistance and operations tooling (planned)

The first AI task contract is tracked in [#26](https://github.com/westondunn/nextup-get-hired/issues/26). Nothing else here has an issue.

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
