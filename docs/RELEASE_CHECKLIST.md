# NextUp release checklist

These are the gates that must be met before NextUp's integrations are described as publicly supported. A gate is checked only when the evidence is linked next to it. A merged pull request or a closed issue is not evidence on its own.

**Snapshot date: 2026-11-13, taken at commit `4bbff43`.** No gate is met yet. The ordered work is in the [roadmap](ROADMAP.md); scope and acceptance criteria are in the linked issues.

## Safety baseline

- [ ] The default application works with no external service, model credential or integration configured. Evidence: pending.
- [ ] Every shipped configuration publishes ports on the loopback interface only. Evidence: pending.
- [ ] Credential-related and state-changing requests are refused outside the local session boundary ([#8](https://github.com/westondunn/nextup-get-hired/issues/8)). Evidence: pending.
- [ ] `SECURITY.md` states the authentication limits as they are at the release commit. Evidence: pending.
- [ ] Pinned migration history is unchanged and every schema change is a new revision applied through the guard. Evidence: pending.
- [ ] The verification run's secret audit passes at the release commit. Evidence: pending.

## Google connection

- [ ] The OAuth client type, redirect URI, scopes and consent constraints are documented from current official Google documentation ([#9](https://github.com/westondunn/nextup-get-hired/issues/9)). Evidence: pending.
- [ ] Connect, status, test, reauthorize and disconnect with revocation are implemented and tested with mocked provider calls ([#10](https://github.com/westondunn/nextup-get-hired/issues/10), [#11](https://github.com/westondunn/nextup-get-hired/issues/11)). Evidence: pending.
- [ ] Tokens are stored server-side, encrypted at rest, and never returned to the browser or written to logs ([#10](https://github.com/westondunn/nextup-get-hired/issues/10)). Evidence: pending.
- [ ] Only read-only Gmail and Calendar scopes are requested. Evidence: pending.
- [ ] Settings shows connection state, granted capabilities, last successful sync and actionable errors, with accessibility coverage ([#12](https://github.com/westondunn/nextup-get-hired/issues/12)). Evidence: pending.
- [ ] Calendar import and display are tested across UTC and America/Chicago daylight-saving boundaries ([#13](https://github.com/westondunn/nextup-get-hired/issues/13)). Evidence: pending.
- [ ] The setup and rollback instructions have been followed on a clean machine, with a dated record for each platform claimed ([#14](https://github.com/westondunn/nextup-get-hired/issues/14)). Evidence: pending.

## Verification

- [ ] The full disposable-stack verification passes at the release commit on a hosted runner. Evidence: pending.
- [ ] Checks that were not run are listed with reasons. Evidence: pending.
- [ ] No live account or personal data was used in any automated test. Evidence: pending.

## Documentation and public claims

- [ ] The README status table matches the evidence above. Evidence: pending.
- [ ] `docs/DEVELOPMENT.md` describes hosted CI and the branching guide accurately ([#5](https://github.com/westondunn/nextup-get-hired/issues/5)). Evidence: pending.
- [ ] The contribution policy is stated in one place and matches the README ([#6](https://github.com/westondunn/nextup-get-hired/issues/6)). Evidence: pending.
- [ ] Wiki summaries are published from the merged documents, each recording its source commit and synchronization date. Evidence: pending; see [wiki drafts](wiki/README.md).

## Not part of this release

Portable n8n workflows and optional AI and operations tooling are planned in the [roadmap](ROADMAP.md) and have no gates here yet.
