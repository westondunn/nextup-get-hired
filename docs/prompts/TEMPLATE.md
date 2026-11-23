# Prompt template

Copy this file into `open/`, `proposed/`, or `discovery/` and replace every bracketed value.
Keep metadata values on one line so the standard-library validator can read them.

```markdown
---
work_id: [unique-kebab-case-id]
status: [live|proposed|discovery]
issue: [number|pending]
primary_model: [gpt-6.2-astra|gpt-6.2-sol|gpt-6.1-terra]
reasoning_effort: ultra
validation_model: [gpt-6.2-astra|gpt-6.2-sol|gpt-6.1-terra|none|human]
depends_on: [comma-separated work IDs or none]
approval_gates: [comma-separated gates or none]
canonical_sources: [comma-separated repository paths and issue URLs]
last_reviewed_commit: [40-character commit]
---

# [Imperative task title]

## Outcome

[Observable result and the user or maintainer it serves.]

## Baseline and authority

[How to refresh `origin/main`, the live issue, accepted decisions, and current evidence.]

## Scope

[Bounded work that belongs in this reviewable change.]

## Non-goals

[Nearby work that must not be folded into this change.]

## Interfaces and data flow

[Routes, types, schema, capabilities, systems receiving data, and preservation rules.]

## Safety and approval gates

[Secrets, egress, migrations, destructive actions, external mutations, and explicit stops.]

## Implementation steps

[Decision-complete sequence, including branch and pull-request behavior.]

## Verification

[Specific tests and checks; distinguish approved checks from gated checks.]

## Documentation and evidence

[Canonical documents, issue evidence, checks not run, and public-claim limits.]

## Stop conditions

[Conditions requiring maintainer input rather than an assumption.]
```

Field meanings and the universal execution boundary are in [README.md](README.md).
