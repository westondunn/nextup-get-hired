# Read-only correspondence capability contract

This contract defines the requirements for importing mail into NextUp. It follows [decision 0002](decisions/0002-standards-first-interoperability.md) and is proposed for review in [#24](https://github.com/westondunn/nextup-get-hired/issues/24). See [Integrations and compatibility](INTEGRATIONS.md) for implementation and support status.

## Operations and permissions

| Clause | Requirement |
| --- | --- |
| List | Required. List stable message references within the configured import scope. Use bounded pages and report whether the scan is complete or has a continuation. |
| Fetch | Required. Read a message by its reference and return the normalized fields below. Reads must leave mailbox state, including read flags and labels, intact. |
| Account address | Optional. Return the mailbox owner's address when the provider can establish it. Declare whether direction can be determined independently, for example from provider metadata. An address is insufficient as the sole basis for recognizing sent mail from aliases. |
| Incremental sync | Optional. Declare whether the provider supplies a change cursor or the adapter uses a bounded rescan. Document the coverage limits and how an interrupted scan resumes. |
| Credential permissions | Declare the operations NextUp uses and the actual scopes or permissions of the credential separately. Identify broader access explicitly and report unknown permissions as unknown. Prefer the narrowest usable grant and surface missing required access. |

**Application-level read-only behavior is not the same as a read-only credential.** NextUp's import never sends mail, marks it read, labels it or otherwise changes the mailbox, even if the credential permits those operations. Mail authorization conveys no calendar or processor authorization.

## Normalized message and data flow

The adapter reads from the mailbox provider and returns only the fields below to NextUp's local import pipeline for storage in `communications`, contact and application matching, and NextUp's own detection. Optional values may be absent. For optional flags, absence means unknown.

| Field | Requirement |
| --- | --- |
| Provider and mailbox namespace | Required context supplied by the connection. Use a stable mailbox identity independent of the current credential and keep it distinct from other mailboxes and providers. |
| Message ID | Required. Keep the provider's original stable message identifier as an opaque value. |
| Thread ID | Optional. Keep the original opaque provider value in the same mailbox namespace. A thread can contain multiple messages. |
| Sender and recipient | Optional sender name, sender address and recipient address for local matching. |
| Subject and body | Optional bounded text. Document any truncation, text conversion or excerpt fallback. |
| Received time | Optional timezone-aware provider timestamp normalized to UTC. Keep the actual import time separate if the provider timestamp is absent or invalid. |
| Sent and auto-reply flags | Optional provider-derived indicators for direction and detection. |

Identify a message by provider, mailbox namespace and message ID together. Preserve provenance when a connection is removed. Keep separate records for equal IDs in different namespaces. Any cross-provider matching would need independent evidence.

Treat message text and headers as untrusted input. Render them as inert text, avoid attachment downloads and remote content loads, and exclude message content, raw provider payloads and credentials from default logs and user-facing errors. The adapter sends none of the normalized fields to any other processor. The [external classifier interface](CORRESPONDENCE_SYNC.md) is a separate path with its existing contract. Calendar imports require a separate contract.

## Sync and preservation

- **Duplicates and retries.** Import the same identity idempotently across repeated pages, partial failures and concurrent runs. Keep a durable checkpoint only for work already accounted for in local storage. A retry can replay committed work without creating rows or replacing user edits.
- **Out-of-order delivery.** Accept messages with equal or older timestamps within the declared import coverage. Advance a cursor only after the covered pages are accounted for. For a bounded rescan, overlap the scan window, deduplicate by identity and document how far back late deliveries can be found.
- **Provider deletions.** A missing result or provider deletion leaves previously imported records intact. A message listed and then removed can be recorded as missing for that scan. Avoid treating a mailbox-wide failure as a message deletion.
- **Cursors.** Scope progress to the mailbox and import filter. Preserve continuation for incomplete pages. If a cursor expires or the filter changes, rebuild it from a documented rescan that retains all local records. Keep progress for different providers and mailboxes independent.
- **Local records.** Re-sync, retry, disconnect and provider changes preserve imported records, user edits and status, existing application and contact links, and NextUp's own detection. Disconnect stops future reads through that connection and clears or disables its credentials. A provider change starts separate progress without moving existing data to the new provider. Reconnecting the same mailbox uses its existing namespace.

## Shared errors

Expose a stable category and a short, safe explanation. Include partial import counts when applicable. A failed read preserves existing data and leaves unprocessed work eligible for retry.

| Category | What the user sees |
| --- | --- |
| `disabled`, `fixture_mode` | Import is off, or fixture mode prevents live reads. |
| `not_configured` | Set up or reconnect the mailbox before syncing. |
| `unauthorized` | The credential was rejected or revoked. Reauthorize the connection. |
| `wrong_scope` | The required read permission is missing. Review the grant before retrying. |
| `connection_error` | NextUp could not read or update the saved connection. Check connection settings. |
| `network_error`, `provider_unavailable` | The provider could not be reached, is rate limiting, or is temporarily unavailable. Retry later. |
| `provider_rejected` | The provider rejected the request. Check the import settings if it persists. |
| `message_missing` | A listed message is no longer available. Sync can continue with the other messages. |
| `cursor_expired` | Sync progress expired. Resume with the documented rescan. |
| `too_large`, `invalid_response` | The provider response exceeded a limit or could not be read. Report incomplete work without exposing message content. |

## Gmail mapping

Compared with main at `6e778c6`. The source is [gmail.py](../backend/app/sources/gmail.py), with credential resolution in [google_credentials.py](../backend/app/google_credentials.py) and import behavior in [correspondence_tasks.py](../backend/app/correspondence_tasks.py).

| Clause | Current Gmail behavior | Gap |
| --- | --- | --- |
| List | `list_message_refs` returns bounded Gmail message and thread IDs for a query. | The worker gets neither a continuation nor a signal that the listing hit its cap. |
| Fetch | `fetch_message` uses a Gmail read endpoint and `parse_message` normalizes the result. | A missing message is handled as a generic rejection and can stop the batch. |
| Account address | `profile_email` can read the primary address. The worker uses the address when classifying older stored mail and derives direction for new imports from Gmail's `SENT` label. | No shared capability declaration. |
| Incremental sync | The worker uses a Gmail `after:` query based on the stored timestamp or initial lookback. | Coverage is tied to Gmail and there is no provider change cursor or overlap guarantee. |
| Credential permissions | Gmail requests `gmail.readonly`. Stored grants track capability scopes, and the refresh check looks for the Gmail scope when scope information is present. A configured token can also be used. | No shared declaration of effective permissions, including broader or unknown access for configured credentials. |
| Message fields | `ParsedMessage` returns the message and thread IDs, names and addresses, subject, bounded body, time and flags. It takes the first parsed recipient, can fall back to a snippet, and derives auto-replies from `Auto-Submitted`. | Optional strings use empty values. Missing or invalid timestamps can become the epoch or current time. Boolean fields do not distinguish unknown from false. |
| Identity and provenance | The worker stores `source=gmail`, the original message ID and optional thread ID. | Deduplication uses source and message ID without a mailbox namespace. |
| Data flow and untrusted input | The worker imports locally and uses local rules. Gmail fetches message payloads without a separate attachment or remote content fetch, converts HTML to text and uses fixed provider error messages. The adapter sends no fields to a classifier. | There is no shared normalization or redaction guarantee across providers. |
| Duplicates and retries | The worker locks the settings row and skips IDs already imported. A source error can leave a partial import with the previous cursor. | The pending batch does not deduplicate repeated IDs within the same listing. |
| Out-of-order delivery | The cursor advances to the newest imported timestamp after processing the listed batch. | Older arrivals can fall outside the next query, and a capped listing can appear complete. |
| Provider deletions | Absence from the listing does not remove stored rows. | A fetch returning HTTP 404 maps to `provider_rejected`, so later messages can be delayed. |
| Cursor lifecycle | The singleton settings row holds the Gmail query and timestamp. Changing the query resets progress to the initial lookback. | No per-mailbox continuation or shared checkpoint and recovery semantics. |
| Local records | The worker skips already imported messages and can fill missing local detection. | No disconnect or provider switch flow demonstrates preservation across connection changes. |
| Shared errors | `SourceError` codes surface through sync status. Gmail already emits several shared categories. Credential resolution also uses `not_connected`, `needs_reauthorization`, `capability_not_granted`, `connection_unreadable` and `connection_not_updated`. | No shared mapping. For example, a refresh rejected with HTTP 400 can surface as `provider_rejected` even when the grant was revoked. Connection-specific statuses need mapping to setup, reauthorization, permission or connection errors. |

The storage shape for per-connection settings and coexistence with the classifier's `gmail_message_id` key are open decisions. This contract does not select a protocol or design a migration.

## Required synthetic adapter tests

Every adapter must pass these tests at the adapter and local import boundary, using fixtures and simulated provider responses.

| Case | Expected result |
| --- | --- |
| Duplicate delivery | Repeat a reference within a page, across pages and on retry. Keep one row per identity. Equal IDs from different mailboxes or providers remain distinct. |
| Out-of-order delivery | Deliver an older and an equal-timestamp message after a newer one within the declared coverage. Import each once, including across a page or batch limit. |
| Revoked credential | Reject the grant and verify the reauthorization status, unchanged checkpoint for unprocessed work and preserved local data. |
| Provider outage | Interrupt a paged scan with a timeout, rate limit or server error. Show a retryable status and resume with no gaps or duplicates. |
| Preservation of user edits | Edit a record, link it to an application and contact, and save its detection. Replay the message, disconnect and switch providers. The original row, its links, edits and detection survive. |
| Provider deletion and cursor recovery | Remove a listed message before fetch and expire a cursor. Preserve imported records, process later messages and recover using the documented rescan. |
| Permissions and normalization | Simulate broader, unknown and missing grants, absent optional fields and hostile message content. Verify permission reporting, inert bounded text, read-only mailbox requests and absence of message content in logs or processor requests. |
