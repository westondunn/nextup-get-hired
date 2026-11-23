---
work_id: live-12-google-settings-lifecycle
status: live
issue: 12
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: gpt-6.1-terra
depends_on: live-11-google-connection-lifecycle
approval_gates: full-verification, visual-accessibility-validation
canonical_sources: frontend/src/hub/GoogleConnectionCard.tsx, frontend/src/hub/google-api.ts, docs/decisions/0003-google-connection.md, https://github.com/westondunn/nextup-get-hired/issues/12
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Complete Google lifecycle controls in Settings

## Outcome

Settings presents every accepted #11 lifecycle state with accessible test, reauthorize, and
disconnect actions, granted capabilities, last-success/staleness information, and actionable errors.

## Baseline and authority

Refresh `origin/main`, issue #12, the accepted #11 interface, and PR #56's existing connection card,
tests, and browser flow. Rebaseline stale issue text that still says no connect control exists.

## Scope

- Extend `GoogleConnectionCard` and its API module rather than rebuilding them.
- Render each backend state distinctly and announce status changes.
- Add confirmation and clear failure feedback for disconnect; keep reauthorization in the existing
  browser navigation flow.
- Correct unconditional locality copy where an enabled integration sends data to Google.

## Non-goals

No backend lifecycle invention, new scopes, general Settings redesign, live-provider validation,
or support claim.

## Interfaces and data flow

Use only the accepted #11 response/actions. Keep secrets out of component state except the existing
one-time client-secret input and out of browser storage. Render stored URLs only through `safeHref`.

## Safety and approval gates

Preserve the local-session boundary. Destructive disconnect needs an accessible confirmation and
must not delete imported records. Full browser verification and hands-on accessibility validation
require their named approvals; no live Google account is authorized.

## Implementation steps

1. Map every lifecycle state/action to UI copy, focus behavior, and accessible announcement.
2. Extend the existing API types and card with the accepted backend contract.
3. Add component and mocked browser-flow coverage, including failure recovery.
4. Open a review-ready feature PR and stop before approval or merge.

## Verification

Run targeted Vitest, frontend typecheck/build/format, and safe backend contract tests. Use Terra
Ultra for keyboard, focus, zoom/reflow, and screen-reader-oriented inspection after implementation.
Request approval before Playwright through the disposable stack.

## Documentation and evidence

Update setup/troubleshooting drafts and release-checklist evidence without saying Google is
available or supported. Record mocked versus hands-on evidence separately.

## Stop conditions

Stop if #11's interface is not accepted, a UI action would bypass the session, imported data could
be deleted, or validation would require a live account.
