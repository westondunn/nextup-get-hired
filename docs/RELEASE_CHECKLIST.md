# NextUp release checklist

These are the gates that must be met before NextUp, or any of its integrations, is described as publicly supported. A gate is checked only when the evidence is linked next to it. A merged pull request or a closed issue is not evidence on its own.

**Snapshot date: 2026-11-14, last reconciled at commit `c143b87`.** Six gates are met; the rest are open. On 2026-11-17, at `4589435`, the compatibility-matrix gates were added and the evidence for the local-session gate was replaced with a run at that commit; no other gate was re-examined. A gate that states a target is met by a recorded result, never by the target being written down. The ordered work is in the [roadmap](ROADMAP.md); scope and acceptance criteria are in the linked issues.

## Core application

The maintainer accepted the [core first-run design](CORE_ONBOARDING.md#validation) tracked in [#28](https://github.com/westondunn/nextup-get-hired/issues/28). The gates below require dated workflow, platform and user-session results, with accessibility evidence for each new screen. Link each validation issue and its results when available.

- [ ] The core workflows work with no external service, model credential, integration or optional tool configured, shown by a recorded run that lists the workflows exercised ([#28](https://github.com/westondunn/nextup-get-hired/issues/28)). Evidence: pending.
- [ ] The guided setup has been followed on a clean machine, with a dated record for each platform claimed ([#28](https://github.com/westondunn/nextup-get-hired/issues/28)). Evidence: pending.
- [ ] Representative users have completed the guided setup, with results recorded separately from the target number of sessions ([#28](https://github.com/westondunn/nextup-get-hired/issues/28)). Evidence: pending.

## Safety baseline

- [ ] Every shipped configuration publishes ports on the loopback interface only. Evidence: pending.
- [x] Requests to a non-local host name and cross-origin state-changing requests are refused ([#8](https://github.com/westondunn/nextup-get-hired/issues/8)). Evidence: merged in [#20](https://github.com/westondunn/nextup-get-hired/pull/20) as `baf9028`; [hosted CI run on `main`](https://github.com/westondunn/nextup-get-hired/actions/runs/43509731795), which includes the integration, browser and secret-audit checks; local probes of the development stack are recorded in the pull request.
- [x] Integration and credential routes require a local session ([#18](https://github.com/westondunn/nextup-get-hired/issues/18)). Evidence: [hosted CI run on `main`](https://github.com/westondunn/nextup-get-hired/actions/runs/43777493105) at `4589435`, the commit this gate was last checked against. In that run `backend/tests/test_local_session.py` passed: each of the five routes below refuses without a session, is reached with one and refuses again after the session ends, and `test_only_the_intended_routes_require_a_session` finds the requirement on exactly those five and on every Google route except the callback. The live-stack session test (`backend/tests/test_integration.py`), the browser tests (`frontend/tests/session.spec.ts`, `frontend/tests/google.spec.ts`) and the secret audit passed in the same run. The five routes are the two that change or run mail and calendar sync (`PUT /api/correspondence`, `POST /api/correspondence/sync`) and the Google client and connection routes (`GET /api/google/connection`, `PUT /api/google/client`, `POST /api/google/connect`). The address Google sends the browser back to cannot require the session; that exception is in [decision 0001](decisions/0001-local-session-boundary.md) and [SECURITY.md](../SECURITY.md). Earlier evidence, for the two mail and calendar routes only: the setup code and session routes were merged in [#22](https://github.com/westondunn/nextup-get-hired/pull/22) as `81ac008`, and the session requirement and Settings prompt in [#31](https://github.com/westondunn/nextup-get-hired/pull/31) as `7370e9a`, with a [hosted CI run on `main`](https://github.com/westondunn/nextup-get-hired/actions/runs/43538353763) at `7370e9a` and local probes of the development stack recorded in both pull requests. No local probe of the Google routes is cited here. A route added later for a connection must be added to the same requirement, and this gate must be rechecked at the release commit.
- [ ] `SECURITY.md` states the authentication limits as they are at the release commit. Evidence: pending.
- [ ] Pinned migration history is unchanged and every schema change is a new revision applied through the guard. Evidence: pending.
- [ ] The verification run's secret audit passes at the release commit. Evidence: pending.

## Compatibility matrix

These gates apply to every release. The release maintainer records the inventory comparison and reviews support evidence under the [re-validation policy](INTEGRATIONS.md#support-evidence-and-re-validation).

- [ ] Every integration present in the code at the release commit has a row in [INTEGRATIONS.md](INTEGRATIONS.md), including a provider reached only through a shared module ([#27](https://github.com/westondunn/nextup-get-hired/issues/27)). Evidence: pending.
- [ ] Each row's implementation status matches the code and the shipped configurations at the comparison commit named in the snapshot line of [INTEGRATIONS.md](INTEGRATIONS.md). That commit is an ancestor of the release commit, and nothing listed under [the comparison commit](INTEGRATIONS.md#the-comparison-commit) has changed between the two; if something has, the table is compared again first ([#27](https://github.com/westondunn/nextup-get-hired/issues/27)). Evidence: pending.
- [ ] No row says Tested without a linked, dated evidence record that names the NextUp version, and no row describes an integration as supported because a protocol name, passing unit tests or a successful connection exist ([#27](https://github.com/westondunn/nextup-get-hired/issues/27)). Evidence: pending.
- [ ] The comparison of the table with the code and with the evidence it cites is recorded with the comparison commit and the date, in the pull request that moves the snapshot line, and that pull request is linked here ([#27](https://github.com/westondunn/nextup-get-hired/issues/27)). Evidence: pending.

- [ ] The release pull request records the candidate commit, review date and outcome for every row. Each claimed status has current evidence, and claims with missing, stale or failing evidence are narrowed or withdrawn. Evidence: pending.

## Every connection that is offered

These apply to each integration a release lets users enable. The Google gates below are the first instance.

- [ ] The integration has a complete profile in [INTEGRATIONS.md](INTEGRATIONS.md), with its support status, configuration coverage and known limitations ([#27](https://github.com/westondunn/nextup-get-hired/issues/27)). Evidence: pending.
- [ ] The profile states what the credential actually permits and every destination that receives data ([#27](https://github.com/westondunn/nextup-get-hired/issues/27)). Evidence: pending.
- [ ] Connect, reauthorize, disconnect and revocation are tested, including a credential revoked at the provider. Evidence: pending.
- [ ] Authoritative records, user edits and approved content are preserved across disconnect, retry, duplicate delivery and a change of provider ([#24](https://github.com/westondunn/nextup-get-hired/issues/24)). Evidence: pending.
- [ ] One capability is never enabled by another: calendar access is not inferred from mail access, and neither authorizes AI processing. Evidence: pending.

## Google connection

- [x] The OAuth client type, redirect URI, scopes and consent constraints are documented from current official Google documentation ([#9](https://github.com/westondunn/nextup-get-hired/issues/9)). Evidence: [PR #46](https://github.com/westondunn/nextup-get-hired/pull/46) proposed [decision 0003](decisions/0003-google-connection.md) from sources read on 2026-11-14. [PR #47](https://github.com/westondunn/nextup-get-hired/pull/47) recorded acceptance that day at [`bab594e`](https://github.com/westondunn/nextup-get-hired/commit/bab594ed87a4b97af05ff92268d36edd9973ef4e). Google changes its documentation, so the sources must be re-read at the release commit.
- [ ] Connect, status, test, reauthorize and disconnect with revocation are implemented and tested with mocked provider calls ([#10](https://github.com/westondunn/nextup-get-hired/issues/10), [#11](https://github.com/westondunn/nextup-get-hired/issues/11)). Evidence: pending.
- [ ] Tokens are stored server-side, encrypted at rest, and never returned to the browser or written to logs ([#10](https://github.com/westondunn/nextup-get-hired/issues/10)). Evidence: pending.
- [ ] Only read-only Gmail and Calendar scopes are requested. Evidence: pending.
- [ ] Settings shows connection state, granted capabilities, last successful sync and actionable errors, with accessibility coverage ([#12](https://github.com/westondunn/nextup-get-hired/issues/12)). Evidence: pending.
- [x] Calendar import and display are tested across UTC and America/Chicago daylight-saving boundaries ([#13](https://github.com/westondunn/nextup-get-hired/issues/13)), and the defects those tests found are corrected ([#38](https://github.com/westondunn/nextup-get-hired/issues/38), [#39](https://github.com/westondunn/nextup-get-hired/issues/39)). Evidence: the tests merged in [#40](https://github.com/westondunn/nextup-get-hired/pull/40) as `325cc46`; [#39](https://github.com/westondunn/nextup-get-hired/issues/39) was corrected in [#42](https://github.com/westondunn/nextup-get-hired/pull/42) as `be66581`, and [#38](https://github.com/westondunn/nextup-get-hired/issues/38) in [#48](https://github.com/westondunn/nextup-get-hired/pull/48) and [#49](https://github.com/westondunn/nextup-get-hired/pull/49) as `c143b87`; [hosted CI run on `main`](https://github.com/westondunn/nextup-get-hired/actions/runs/43672928458) at `c143b87`, with no expected failure left in either suite. The tests use synthetic events, cover no zone east of UTC and include no browser test; no live calendar has been used. This must be rechecked at the release commit.
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
- [x] `docs/DEVELOPMENT.md` describes hosted CI and the branching guide accurately ([#5](https://github.com/westondunn/nextup-get-hired/issues/5)). Evidence: merged in [#33](https://github.com/westondunn/nextup-get-hired/pull/33) as `ddb1022`; [hosted CI run on `main`](https://github.com/westondunn/nextup-get-hired/actions/runs/43545101394) at `314d8b8`, the first run that includes it. The development notes link the guide and cite a hosted run; branch naming is still not enforced. This reflects the documents at that commit; it must be rechecked at the release commit.
- [x] The contribution policy is stated in one place and matches the README ([#6](https://github.com/westondunn/nextup-get-hired/issues/6)). Evidence: merged in [#36](https://github.com/westondunn/nextup-get-hired/pull/36) as `e9628bd`; [hosted CI run on `main`](https://github.com/westondunn/nextup-get-hired/actions/runs/43650497960). [CONTRIBUTING.md](../CONTRIBUTING.md) states that outside contributions are not being accepted yet, and the README says the same in one line and links to it. This reflects the documents at that commit; it must be rechecked at the release commit.
- [ ] Wiki summaries are published from the merged documents, each recording its source commit and synchronization date. Evidence: pending; see [wiki drafts](wiki/README.md).

## Not part of this release

Workflow access, operations tooling, sending mail, wider calendar synchronization, additional providers and MCP access are listed in the [roadmap](ROADMAP.md) as untracked or deferred, and have no gates here.
