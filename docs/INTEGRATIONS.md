# Integrations and compatibility

This is the canonical record of what NextUp can connect to, what has actually been tested, and how that is described. The direction behind it is in [decision 0002](decisions/0002-standards-first-interoperability.md). The process for keeping it current is tracked in [#27](https://github.com/westondunn/nextup-get-hired/issues/27).

**Snapshot: 2026-11-13, commit `81ac008`. No integration has a support status. Every integration is switched off in every shipped configuration, and there is no supported way to enable one.**

NextUp's core does not need any of these. The workspace is intended to be useful with nothing connected.

## Two separate questions

Every integration is described on two independent axes.

**Implementation status** says what is in the code:

| Value | Meaning |
| --- | --- |
| Not implemented | No code exists |
| Implemented, disabled | Code and unit tests exist; it is off in every shipped configuration and cannot be enabled in a supported way |
| Available | A user can enable it by a documented path |

**Support status** says what has been validated for public use:

| Value | Meaning |
| --- | --- |
| None | Nothing has been validated. This is the default |
| Experimental | It can be enabled by a documented path, validation is incomplete, and it may break. Its known limits are listed |
| Tested | The profile below was validated on a named NextUp version, and the evidence is linked |
| Custom connection | The user supplies an endpoint or server that follows a documented protocol or API profile. NextUp offers the settings and a connectivity check. That particular server or model has not been tested, and no claim is made that it works |

An integration that is implemented but disabled is never described as supported because its unit tests pass. The evidence each support status requires, and how often it is re-validated, are still to be defined in [#27](https://github.com/westondunn/nextup-get-hired/issues/27).

## Capability vocabulary (proposed)

These names are proposals, to be settled in [#24](https://github.com/westondunn/nextup-get-hired/issues/24) and [#27](https://github.com/westondunn/nextup-get-hired/issues/27). They exist so that one capability is never inferred from another.

| Capability | Meaning |
| --- | --- |
| Correspondence: read | Import messages. Nothing is changed in the mailbox |
| Correspondence: send | Submit mail. Separate from reading; not implemented and not planned in the current issues |
| Calendar: read | Import events from a calendar service |
| Calendar: file import or export | Exchange an iCalendar file. Not continuous synchronization |
| Job listings: fetch | Read postings from a job source |
| AI task: *name* | Send selected content to a processor the user chose, for one named task |
| Workflow access | Another tool reads or writes NextUp through a defined interface |

## Current state

| Integration | Capability | Protocol or API | Implementation status | Support status | Notes |
| --- | --- | --- | --- | --- | --- |
| Gmail | Correspondence: read | Gmail API, scope `gmail.readonly` | Implemented, disabled | None | `backend/app/sources/gmail.py`. Uses a refresh token supplied through configuration; no consent flow, stored token or revocation. Connection work: [#9](https://github.com/westondunn/nextup-get-hired/issues/9)–[#12](https://github.com/westondunn/nextup-get-hired/issues/12), [#14](https://github.com/westondunn/nextup-get-hired/issues/14) |
| Google Calendar | Calendar: read | Calendar API, scope `calendar.readonly` | Implemented, disabled | None | `backend/app/sources/google_calendar.py`. Shares the Gmail client and token today. Daylight-saving coverage: [#13](https://github.com/westondunn/nextup-get-hired/issues/13) |
| Adzuna | Job listings: fetch | Adzuna API | Implemented, disabled | None | `backend/app/sources/adzuna.py`. Live fetching is off in every shipped configuration; CI uses bundled synthetic fixtures |
| Greenhouse boards | Job listings: fetch | Greenhouse public postings | Implemented, disabled | None | `backend/app/sources/greenhouse.py`. Same switch as above |
| Employer boards | Job listings: fetch | Public posting APIs | Implemented, disabled | None | `backend/app/sources/employer_boards.py`. Same switch as above |
| External classifier | AI task: classification hint | Database contract in [CORRESPONDENCE_SYNC.md](CORRESPONDENCE_SYNC.md) | Implemented, disabled | None | Refused in every environment. NextUp ships no classifier |
| Other mailboxes (IMAP, other provider APIs) | Correspondence: read | Undecided | Not implemented | None | Evaluation: [#25](https://github.com/westondunn/nextup-get-hired/issues/25) |
| Sending mail | Correspondence: send | Undecided | Not implemented | None | Deferred; no issue |
| Other calendars (CalDAV, iCalendar files, other provider APIs) | Calendar | Undecided | Not implemented | None | Deferred; no issue |
| AI processor | AI task | Undecided | Not implemented | None | Contract: [#26](https://github.com/westondunn/nextup-get-hired/issues/26) |
| Workflow or assistant access (versioned API, MCP) | Workflow access | Undecided | Not implemented | None | Deferred; no issue |

The Settings view also shows a "CSV Job Import" card. At this commit it describes adding jobs by hand or posting to an API endpoint; it is not a connection to an external service and is not covered by this table.

## Profile template

When an integration can be enabled, it gets a profile with every field below. A profile with gaps cannot be marked Tested.

| Field | What to record |
| --- | --- |
| Capability | From the vocabulary above |
| Protocol or API and version | For example the API version, or the RFC and extensions relied on |
| Authentication | The flow, who owns the client registration, and where credentials are stored |
| What the credential permits | The actual permissions granted, including anything beyond what NextUp uses |
| Supported configurations | Account types, server software and versions, or model and endpoint, that were tested |
| Data destinations | Every system that receives data, and what it receives |
| Retention | What NextUp stores, for how long, and what happens on disconnect |
| Tested NextUp version | Commit or release |
| Evidence | Links to dated validation records and test runs |
| Limitations | Known gaps and unsupported cases |
| Failure behavior | What the user sees and what is preserved when the provider is unavailable, the credential is revoked, or consent is partial |
| Support status | None, Experimental, Tested or Custom connection |

A profile must not describe an integration as local if it sends data to another system. Changing provider never moves existing data to the new processor automatically.

## Profiles

None yet.
