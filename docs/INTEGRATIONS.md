# Integrations and compatibility

This is the canonical record of what NextUp can connect to, what has actually been tested, and how that is described. The direction behind it is in [decision 0002](decisions/0002-standards-first-interoperability.md). The process for keeping it current is tracked in [#27](https://github.com/westondunn/nextup-get-hired/issues/27).

**Snapshot: compared with the code at commit `4589435` on 2026-11-17. No integration has a support status. Every integration is switched off in every shipped configuration, and there is no supported way to enable one.**

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
| Gmail | Correspondence: read | Gmail API, scope `gmail.readonly` | Implemented, disabled | None | `backend/app/sources/gmail.py`. A browser consent flow that stores an encrypted grant exists in the API (`backend/app/google_consent.py`). Sync uses that stored grant when one exists, and otherwise a refresh token supplied through configuration (`backend/app/google_credentials.py`). Settings has a card that saves the user's own Google client and starts the flow (`frontend/src/hub/GoogleConnectionCard.tsx`, [#56](https://github.com/westondunn/nextup-get-hired/pull/56)); in every shipped configuration it reports that no Google account can be connected and offers nothing else. All of it is tested with simulated Google responses only. There is no way to disconnect. Connection work: [#9](https://github.com/westondunn/nextup-get-hired/issues/9)–[#12](https://github.com/westondunn/nextup-get-hired/issues/12), [#14](https://github.com/westondunn/nextup-get-hired/issues/14) |
| Google Calendar | Calendar: read | Calendar API, scope `calendar.readonly` | Implemented, disabled | None | `backend/app/sources/google_calendar.py`. Uses the same stored grant or configuration token as Gmail, and runs only if that grant includes the calendar scope. Daylight-saving tests were added on 2026-11-14 ([#13](https://github.com/westondunn/nextup-get-hired/issues/13)); they found two defects, both since corrected: [#39](https://github.com/westondunn/nextup-get-hired/issues/39) in [#42](https://github.com/westondunn/nextup-get-hired/pull/42), and [#38](https://github.com/westondunn/nextup-get-hired/issues/38) in [#48](https://github.com/westondunn/nextup-get-hired/pull/48) and [#49](https://github.com/westondunn/nextup-get-hired/pull/49) |
| Adzuna | Job listings: fetch | Adzuna search API, with an app ID and key from configuration | Implemented, disabled | None | `backend/app/sources/adzuna.py`. A fetch sends one search, the first target title and the location from the saved profile, and reads one page of 25 results from the US search. Live fetching is off in every shipped configuration; CI serves a bundled synthetic fixture instead. Its automated tests use simulated responses only (`backend/tests/test_adzuna.py`) |
| Greenhouse boards | Job listings: fetch | Greenhouse Job Board API; no credential | Implemented, disabled | None | Two paths read the same API: one board named in configuration (`backend/app/sources/greenhouse.py`), and boards chosen for employer-board discovery (`backend/app/sources/employer_boards.py`). Same switch as Adzuna. CI serves a bundled synthetic fixture for the first path only. Its automated tests use simulated responses only (`backend/tests/test_greenhouse.py`, `backend/tests/test_employer_boards.py`) |
| Lever boards | Job listings: fetch | Lever postings API; no credential | Implemented, disabled | None | `backend/app/sources/employer_boards.py`; there is no separate Lever module. Reached only through employer-board discovery. Reads up to four pages of 250 postings, and stores nothing from a board that fills all four. Same switch as Adzuna. There is no bundled fixture. Its automated tests use simulated responses only (`backend/tests/test_employer_boards.py`) |
| Ashby boards | Job listings: fetch | Ashby job postings API; no credential | Implemented, disabled | None | `backend/app/sources/employer_boards.py`; there is no separate Ashby module. Reached only through employer-board discovery, and only for a board the user adds by hand, because the bundled example list has no Ashby board. Postings that are not marked as listed are left out. Same switch as Adzuna. There is no bundled fixture. Its automated tests use simulated responses only (`backend/tests/test_employer_boards.py`) |
| External classifier | AI task: classification hint | Database contract in [CORRESPONDENCE_SYNC.md](CORRESPONDENCE_SYNC.md) | Implemented, disabled | None | Refused in every environment. NextUp ships no classifier |
| Other mailboxes (IMAP, other provider APIs) | Correspondence: read | Undecided | Not implemented | None | Evaluation: [#25](https://github.com/westondunn/nextup-get-hired/issues/25) |
| Sending mail | Correspondence: send | Undecided | Not implemented | None | Deferred; no issue |
| Other calendars (CalDAV, iCalendar files, other provider APIs) | Calendar | Undecided | Not implemented | None | Deferred; no issue |
| AI processor | AI task | Undecided | Not implemented | None | Contract: [#26](https://github.com/westondunn/nextup-get-hired/issues/26) |
| Workflow or assistant access (versioned API, MCP) | Workflow access | Undecided | Not implemented | None | Deferred; no issue |

Greenhouse, Lever and Ashby are separate services with separate APIs, so each has its own row, although one module (`backend/app/sources/employer_boards.py`) reads all three. That module is not an integration of its own. Employer-board discovery (`backend/app/discovery_api.py`, the Discovery view) fetches the boards the user chooses, either from a bundled list of example boards (`backend/app/employer_catalog.py`: 37 Greenhouse boards and 3 Lever boards at this commit, with no claim that any of them is reachable) or added by hand as a provider and a board token. A request carries the board token and nothing from the profile; postings are compared with the profile after they are read. No validation against a live service is recorded for any of the four job-listing providers.

All job-listing fetching, discovery included, is behind one setting, `NEXTUP_LIVE_JOB_FETCH_ENABLED`. It is `false` in every shipped configuration, and the launcher refuses a configuration that sets it to anything else. While it is off, a choice of boards can be saved, but discovery cannot be switched on or run, and no request is made. In fixture data mode (CI and tests only) discovery is refused, because it has no synthetic fixture.

The Settings view also shows a "CSV Job Import" card. At this commit it describes adding jobs by hand or posting to an API endpoint; it is not a connection to an external service and is not covered by this table.

## Keeping the table current

These rules come from the acceptance criteria of [#27](https://github.com/westondunn/nextup-get-hired/issues/27) and from [decision 0002](decisions/0002-standards-first-interoperability.md). The evidence each support status requires, who records it and how often a row is re-validated are not settled, and nothing in this section settles them.

- Every integration present in the code has a row. A provider reached only through a shared module, as Lever and Ashby are, is still an integration and has its own row.
- Implementation status is read from the code and the shipped configurations at the comparison commit, which is defined below. Support status is never worked out from it: a protocol name, passing unit tests or a successful connection is not evidence of support.
- No row says Tested without a linked, dated evidence record that names the NextUp version.
- Before a release the table is compared with the code and with the evidence it cites, and the comparison is recorded. The gates are in the [release checklist](RELEASE_CHECKLIST.md).

### The comparison commit

The snapshot line names the comparison commit: the commit whose code and shipped configurations the table was last compared with. It is always an earlier commit than the one that records the comparison, because a document cannot contain the identifier of its own commit. "At this commit" in this document means the comparison commit.

The table still describes a later commit as long as nothing it describes has changed since the comparison commit. It is compared again, and the snapshot line is moved, when a later commit changes any of these:

- a file under `backend/app/sources/`;
- any other file that a row or a note under the table cites;
- `backend/app/config.py`, a Compose file, a template under `env/` or `scripts/oss_env.py`, which together decide what a shipped configuration can switch on;
- anything that adds, removes or redirects a request to an external service, wherever it is in the code.

The first three can be checked by listing the files that differ between the comparison commit and the later one:

```sh
git diff --name-only <comparison commit> <later commit> -- backend/app/sources backend/app/config.py 'compose*.yaml' env scripts/oss_env.py <each file the table and its notes cite>
```

If that prints nothing, those files are unchanged. The fourth cannot be checked by path, so it needs a search of the later commit for outbound requests and their hosts. A change to this document alone, including the commit that records a comparison, does not call for another one.

This is only about the table matching the code. It is not the re-validation of a support status, whose evidence and cadence are open in [#27](https://github.com/westondunn/nextup-get-hired/issues/27).

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
