# decompose the optional AI task into consent, adapter, and evaluation work

> Draft only. Do not publish without explicit maintainer approval.

## User problem and intended outcome

Optional classification must not turn a documented contract into an unbounded agent or confuse a
successful connection with useful quality. Outcome: an accepted decomposition defines safe,
separately reviewable implementation and evaluation children.

## Current state

`docs/AI_TASK_CONTRACT.md` defines one classification-hint task, explicit consent, bounded fields,
strict output, a connectivity probe, and separate synthetic quality evidence. No processor exists
and the external classifier is refused everywhere. Reviewed at commit `f9024aa` (`main`) on
2026-11-23.

## Scope

Design children for consent/configuration/provenance; exact-endpoint adapter and strict validator;
asynchronous import integration that preserves manual/rule workflows; and a versioned evaluation
harness/report against the rule-only baseline.

## Non-goals

No provider selection, general chat/agent, tools, URL following, automatic application/message,
consumer-subscription claim, or implementation in this issue.

## Capabilities and data flows

AI task: imported-message classification hint. Only the contract's bounded subject/excerpt may go
to the exact user-selected endpoint after separate recorded consent.

## Dependencies and unresolved decisions

Decide storage ownership, credential handling, async trigger, retention, and which controlled
reference endpoint can support connectivity evidence. Core release does not depend on this work.

## Acceptance criteria

- Each child has exact schemas, failure behavior, provenance, and no-fallback rules.
- Connectivity, quality, and support claims remain separate.
- Provider changes never replay history automatically.
- Evaluation freezes fixtures and mappings before scoring and reports denominators.

## Security, privacy, failure handling and data preservation

Mail permission never implies processor consent. Prompt injection is contained outside the prompt;
no tools or processor-supplied IDs are trusted. Failure creates no new hint and preserves existing
records and decisions.

## Evidence expected

Reviewed decomposition against every AI task contract and release-checklist clause.

## Documentation affected

AI task contract, integrations matrix, roadmap, and future issue bodies.

## Contributor notes

- Suggested branch: `docs/ai-implementation-plan` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: AI/correspondence contracts and future settings/worker boundaries.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: #3.
- Related completed contract: #26.
- Actual branch and pull request: not created yet.
- Verification evidence: pending.
