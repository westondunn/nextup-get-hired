# NextUp release checklist

These are the gates that must be met before NextUp, or any of its integrations, is described as publicly supported. A gate is checked only when the evidence is linked next to it. A merged pull request or a closed issue is not evidence on its own.

**Snapshot date: 2026-11-13, last reconciled at commit `81ac008`.** One gate is met; the rest are open. A gate that states a target is met by a recorded result, never by the target being written down. The ordered work is in the [roadmap](ROADMAP.md); scope and acceptance criteria are in the linked issues.

## Core application

- [ ] The core workflows work with no external service, model credential, integration or optional tool configured, shown by a recorded run that lists the workflows exercised ([#28](https://github.com/westondunn/nextup-get-hired/issues/28)). Evidence: pending.
- [ ] The guided setup has been followed on a clean machine, with a dated record for each platform claimed ([#28](https://github.com/westondunn/nextup-get-hired/issues/28)). Evidence: pending.
- [ ] Representative users have completed the guided setup, with results recorded separately from the target number of sessions ([#28](https://github.com/westondunn/nextup-get-hired/issues/28)). Evidence: pending.

## Safety baseline

- [ ] Every shipped configuration publishes ports on the loopback interface only. Evidence: pending.
- [x] Requests to a non-local host name and cross-origin state-changing requests are refused ([#8](https://github.com/westondunn/nextup-get-hired/issues/8)). Evidence: merged in [#20](https://github.com/westondunn/nextup-get-hired/pull/20) as `baf9028`; [hosted CI run on `main`](https://github.com/westondunn/nextup-get-hired/actions/runs/43509731795), which includes the integration, browser and secret-audit checks; local probes of the development stack are recorded in the pull request.
- [ ] Integration and credential routes require a local session ([#18](https://github.com/westondunn/nextup-get-hired/issues/18)). Evidence: partial; the session routes exist ([#22](https://github.com/westondunn/nextup-get-hired/pull/22), `81ac008`) but no route requires a session yet.
- [ ] `SECURITY.md` states the authentication limits as they are at the release commit. Evidence: pending.
- [ ] Pinned migration history is unchanged and every schema change is a new revision applied through the guard. Evidence: pending.
- [ ] The verification run's secret audit passes at the release commit. Evidence: pending.

## Every connection that is offered

These apply to each integration a release lets users enable. The Google gates below are the first instance.

- [ ] The integration has a complete profile in [INTEGRATIONS.md](INTEGRATIONS.md), with its support status, tested configurations and known limitations ([#27](https://github.com/westondunn/nextup-get-hired/issues/27)). Evidence: pending.
- [ ] The profile states what the credential actually permits and every destination that receives data ([#27](https://github.com/westondunn/nextup-get-hired/issues/27)). Evidence: pending.
- [ ] Connect, reauthorize, disconnect and revocation are tested, including a credential revoked at the provider. Evidence: pending.
- [ ] Authoritative records, user edits and approved content are preserved across disconnect, retry, duplicate delivery and a change of provider ([#24](https://github.com/westondunn/nextup-get-hired/issues/24)). Evidence: pending.
- [ ] One capability is never enabled by another: calendar access is not inferred from mail access, and neither authorizes AI processing. Evidence: pending.

## Google connection

- [ ] The OAuth client type, redirect URI, scopes and consent constraints are documented from current official Google documentation ([#9](https://github.com/westondunn/nextup-get-hired/issues/9)). Evidence: pending.
- [ ] Connect, status, test, reauthorize and disconnect with revocation are implemented and tested with mocked provider calls ([#10](https://github.com/westondunn/nextup-get-hired/issues/10), [#11](https://github.com/westondunn/nextup-get-hired/issues/11)). Evidence: pending.
- [ ] Tokens are stored server-side, encrypted at rest, and never returned to the browser or written to logs ([#10](https://github.com/westondunn/nextup-get-hired/issues/10)). Evidence: pending.
- [ ] Only read-only Gmail and Calendar scopes are requested. Evidence: pending.
- [ ] Settings shows connection state, granted capabilities, last successful sync and actionable errors, with accessibility coverage ([#12](https://github.com/westondunn/nextup-get-hired/issues/12)). Evidence: pending.
- [ ] Calendar import and display are tested across UTC and America/Chicago daylight-saving boundaries ([#13](https://github.com/westondunn/nextup-get-hired/issues/13)). Evidence: pending.
- [ ] The setup and rollback instructions have been followed on a clean machine, with a dated record for each platform claimed ([#14](https://github.com/westondunn/nextup-get-hired/issues/14)). Evidence: pending.

## Optional AI assistance (only if a release offers it)

- [ ] The task, the fields sent and the processing destination are shown to the user before anything is sent, and consent is recorded separately from mailbox access ([#26](https://github.com/westondunn/nextup-get-hired/issues/26)). Evidence: pending.
- [ ] There is no fallback to another processor, to cloud processing or to a separately billed service without an explicit choice ([#26](https://github.com/westondunn/nextup-get-hired/issues/26)). Evidence: pending.
- [ ] Output quality has been evaluated on labelled synthetic fixtures against a rule-only baseline, and the measured results are recorded separately from any proposed threshold. A successful connection is not accepted as this evidence ([#26](https://github.com/westondunn/nextup-get-hired/issues/26)). Evidence: pending.
- [ ] The manual workflow still works when the processor is unavailable, and no user decision is overwritten. Evidence: pending.

## Verification

- [ ] The full disposable-stack verification passes at the release commit on a hosted runner. Evidence: pending.
- [ ] Checks that were not run are listed with reasons. Evidence: pending.
- [ ] No live account or personal data was used in any automated test. Evidence: pending.

## Documentation and public claims

- [ ] The README status table matches the evidence above. Evidence: pending.
- [ ] No public document or wiki page claims that any AI subscription works, that every email provider works, that NextUp is fully local while an enabled integration sends data elsewhere, that it is production-ready, secure or supported without evidence, or that setup is one click ([#23](https://github.com/westondunn/nextup-get-hired/issues/23)). Evidence: pending.
- [ ] `docs/DEVELOPMENT.md` describes hosted CI and the branching guide accurately ([#5](https://github.com/westondunn/nextup-get-hired/issues/5)). Evidence: pending.
- [ ] The contribution policy is stated in one place and matches the README ([#6](https://github.com/westondunn/nextup-get-hired/issues/6)). Evidence: pending.
- [ ] Wiki summaries are published from the merged documents, each recording its source commit and synchronization date. Evidence: pending; see [wiki drafts](wiki/README.md).

## Not part of this release

Workflow access, operations tooling, sending mail, wider calendar synchronization, additional providers and MCP access are listed in the [roadmap](ROADMAP.md) as untracked or deferred, and have no gates here.
