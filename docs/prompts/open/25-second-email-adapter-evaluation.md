---
work_id: live-25-second-email-adapter-evaluation
status: live
issue: 25
primary_model: gpt-6.2-astra
reasoning_effort: ultra
validation_model: none
depends_on: live-24-correspondence-contract-acceptance
approval_gates: maintainer-recommendation,issue-update
canonical_sources: docs/CORRESPONDENCE_CAPABILITY.md, docs/INTEGRATIONS.md, docs/decisions/0002-standards-first-interoperability.md, https://github.com/westondunn/nextup-get-hired/issues/25
last_reviewed_commit: f9024aacbfead69bf9afafa93877b9a001f7a59a
---

# Evaluate a second read-only email adapter

## Outcome

A bounded, current-primary-source evaluation recommends Microsoft Graph, OAuth-capable generic
IMAP, JMAP, or explicitly recommends no implementation yet.

## Baseline and authority

Refresh issue #25 and confirm #24 is accepted. Use the accepted correspondence contract as the
scorecard and Gmail API as the implemented baseline. Review current official specifications and
provider documentation with dates; do not rely on remembered permissions or compatibility.

## Scope

- Compare Graph, OAuth-capable IMAP, and JMAP consistently for demand evidence, credential breadth,
  non-technical setup, identifier/sync semantics, server/account coverage, and maintenance/testing.
- Keep Outlook.com, Microsoft 365, and on-premises Exchange distinct.
- End with one recommendation or a documented no-build recommendation.

## Non-goals

No adapter implementation, real mailbox, protocol experiment against a personal service, sending,
support claim, or commitment to every server implementing a protocol.

## Interfaces and data flow

Evaluate only `Correspondence: read`. For each candidate, document actual credential permissions,
destinations, storage, paging/cursor behavior, deletion semantics, and contract gaps.

## Safety and approval gates

Use current primary sources and synthetic/local experiments only. Cite review dates and distinguish
standard claims from provider-specific behavior. The maintainer approves the recommendation before
any implementation issue is filed.

## Implementation steps

1. Lock the shared criteria and evidence rubric before scoring.
2. Gather and cite official sources for each candidate.
3. Score candidates, record uncertainty and maintenance cost, and write the recommendation.
4. Open a review-ready documentation PR; do not create an implementation issue automatically.

## Verification

Check every external claim against its cited primary source, every table row against the same rubric,
all links, Markdown, and `git diff --check`. Record experiments separately from support evidence.

## Documentation and evidence

Add the evaluation under `docs/`, update `docs/INTEGRATIONS.md` only if the maintainer accepts a
planned direction, and retain support status `None` without implementation/validation.

## Stop conditions

Stop if #24 is unaccepted, current official sources are unavailable or contradictory, demand
evidence cannot be defined, or the recommendation depends on testing a real mailbox.
