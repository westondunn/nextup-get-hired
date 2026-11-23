# evaluate calendar interoperability beyond Google

> Draft only. Do not publish without explicit maintainer approval.

## User problem and intended outcome

Users should understand whether a portable file exchange or another read-only service is the next
calendar capability, without implying universal compatibility. Outcome: a primary-source
evaluation recommends one bounded path or recommends deferral.

## Current state

Only read-only Google Calendar import exists, disabled and unsupported. CalDAV and iCalendar file
import/export are listed as deferred and have no code or issue. Reviewed at commit `f9024aa`
(`main`) on 2026-11-23.

## Scope

Compare iCalendar file import/export, CalDAV read access, and a second provider API on portability,
credential permissions, recurrence/time-zone fidelity, incremental sync, deletion semantics,
setup burden, and testability.

## Non-goals

No implementation, calendar writes, scheduling automation, or promise to support every server.

## Capabilities and data flows

Calendar: read and Calendar: file import or export are separate candidates. Record every system
that receives event data.

## Dependencies and unresolved decisions

Use the integrations support vocabulary. Decide the short list and demand evidence in the issue;
no live personal calendar is used.

## Acceptance criteria

- Candidates use the same criteria and current primary documentation with review dates.
- Time zones, recurrence, identity, deletion, permissions, and local preservation are compared.
- The report makes one recommendation or explicitly recommends no work.

## Security, privacy, failure handling and data preservation

Flag broad credentials and remote retention. Existing imported events and edits must survive a
provider change. Use synthetic calendars or controlled test servers only.

## Evidence expected

Reviewed evaluation and any controlled experiment clearly labelled as non-support evidence.

## Documentation affected

Evaluation report and, if approved, integrations matrix and roadmap.

## Contributor notes

- Suggested branch: `docs/calendar-interoperability-evaluation` (a suggestion; the actual branch is recorded under Links once created). Naming rules are in the [branching guide](https://github.com/westondunn/nextup-get-hired/blob/main/docs/BRANCHING.md).
- Affected modules: integration documentation.
- Availability: Maintainer-only. Outside contributions are not being accepted yet (see [CONTRIBUTING.md](https://github.com/westondunn/nextup-get-hired/blob/main/CONTRIBUTING.md)).

## Links

- Parent: #3.
- Actual branch and pull request: not created yet.
- Verification evidence: pending.
