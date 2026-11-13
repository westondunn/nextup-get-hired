# NextUp roadmap

This page lists the planned integration outcomes in order. It is public planning for a pre-release project. Outside contributions are not being accepted yet (see the [README](../README.md#development-and-contributions)), so nothing here is an invitation to start work.

**Snapshot date: 2026-11-13, last reconciled at commit `6da6061`.** Status, scope and acceptance criteria live in the linked issues; where this page and an issue disagree, the issue is right. The parent tracking issue is [#3](https://github.com/westondunn/nextup-get-hired/issues/3). There is no GitHub Project for this repository.

An outcome is checked only when its completion gate is met and the evidence is linked. A branch, an open pull request or a closed issue does not check it. Readiness gates for a public release are in the [release checklist](RELEASE_CHECKLIST.md).

Branch names below are suggestions that follow the [branching guide](BRANCHING.md). The branch actually used is recorded in the issue.

## What exists today

- Read-only Gmail and Google Calendar sync are implemented and switched off in every shipped configuration. There is no consent flow, no stored token and no supported way to enable them.
- The API has no authentication and is published on the loopback interface only.
- The optional external classifier interface is described in [CORRESPONDENCE_SYNC.md](CORRESPONDENCE_SYNC.md) and is refused in every environment.
- There is no Google Docs integration, no n8n workflow and no AI-provider integration in the repository.

## P0 — Tracking baseline and safety

- [x] **Outcome: the roadmap and release checklist are published**
  - Tracking: [#4](https://github.com/westondunn/nextup-get-hired/issues/4)
  - Priority and dependencies: P0; none
  - Suggested branch: `docs/4-integration-readiness-roadmap` (actual: `docs/integration-readiness-roadmap`)
  - Contributor notes: `docs/`, `README.md`; documentation only
  - Contribution availability: maintainer-only
  - Complete when: both documents are merged with every link verified, and wiki drafts are staged as unpublished
  - Evidence: merged in [#15](https://github.com/westondunn/nextup-get-hired/pull/15) as `6548863`; [hosted CI run on `main`](https://github.com/westondunn/nextup-get-hired/actions/runs/43491072504); completion record in [#4](https://github.com/westondunn/nextup-get-hired/issues/4). The Home and Roadmap wiki pages were published afterwards; see [wiki/README.md](wiki/README.md)

- [ ] **Outcome: the development notes link to the branching guide and describe hosted CI accurately**
  - Tracking: [#5](https://github.com/westondunn/nextup-get-hired/issues/5)
  - Priority and dependencies: P0; none
  - Suggested branch: `docs/5-branching-adoption`
  - Contributor notes: `docs/DEVELOPMENT.md`, `docs/BRANCHING.md`; no naming check or ruleset change
  - Contribution availability: maintainer-only
  - Complete when: the guide is linked and every hosted-CI statement cites a run
  - Evidence: pending

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

- [ ] **Outcome: requests to a non-local host name and cross-origin state-changing requests are refused**
  - Tracking: [#8](https://github.com/westondunn/nextup-get-hired/issues/8)
  - Priority and dependencies: P0; blocked by [#7](https://github.com/westondunn/nextup-get-hired/issues/7)
  - Suggested branch: `feature/8-local-request-boundary`
  - Contributor notes: `backend/app/main.py` and a new backend module; no frontend change; loopback-only publication does not change
  - Contribution availability: maintainer-only
  - Complete when: each refusal path and each access path is tested and the full verification passes
  - Evidence: pending

- [ ] **Outcome: integration and credential routes require a local session**
  - Tracking: [#18](https://github.com/westondunn/nextup-get-hired/issues/18)
  - Priority and dependencies: P0; blocked by [#8](https://github.com/westondunn/nextup-get-hired/issues/8)
  - Suggested branch: `feature/18-local-session`
  - Contributor notes: `scripts/local.py`, a new backend module and migration, `backend/app/correspondence.py`, `frontend/src/hub/SettingsView.tsx`
  - Contribution availability: maintainer-only
  - Complete when: session start, expiry and refusal are tested, the secret audit passes, and the Settings prompt has accessibility coverage
  - Evidence: pending

## P1 — Google connection

- [ ] **Outcome: the bring-your-own Google OAuth client flow and token storage are decided**
  - Tracking: [#9](https://github.com/westondunn/nextup-get-hired/issues/9)
  - Priority and dependencies: P1; blocked by [#7](https://github.com/westondunn/nextup-get-hired/issues/7)
  - Suggested branch: `docs/9-google-oauth-adr`
  - Contributor notes: decision record under `docs/`; must cite current official Google documentation
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

## P2 — Portable n8n workflows (planned, not yet tracked)

No issues have been filed. They will be created when the P1 work is under way.

- Sanitized, versioned workflow exports for optional mail labelling, grounded summaries and reviewed drafts.
- A narrow, authenticated contract between NextUp and a workflow, with NextUp remaining the authoritative record.
- Read-only import kept separate from any mailbox change. No automatic sending and no automatic job applications.
- The external classifier contract in [CORRESPONDENCE_SYNC.md](CORRESPONDENCE_SYNC.md) is preserved: hints never override NextUp's detection or existing links.

## P3 — Optional AI and operations tooling (planned, not yet tracked)

No issues have been filed.

- A model-provider adapter only where needed, with local models as the default and cloud processing as an explicit opt-in.
- A separate evaluation of AI quality against labelled synthetic fixtures and a rule-only baseline, so that working connectivity is not mistaken for demonstrated quality.
- Documented boundaries for optional operations tools before any connector is built.

## Separate, approval-gated work

Automated branch-name checking and any change to the `main` ruleset are described as proposals in the [branching guide](BRANCHING.md). They are not scheduled here and need maintainer approval before they start.
