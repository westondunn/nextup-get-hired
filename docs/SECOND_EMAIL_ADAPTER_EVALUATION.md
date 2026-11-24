# Second read-only email adapter evaluation

**Recommendation for #25: defer implementation.** Microsoft Graph offers the clearest documented read-only grant for a body-bearing import. The public record does not identify a NextUp user who needs one of these specific mailbox configurations, and NextUp still lacks the mailbox identity and checkpoint handling needed to demonstrate safe coexistence with Gmail. This is a recommendation for maintainer review. [Issue #25][issue] · [Accepted correspondence contract][contract]

The evaluation covers **Correspondence: read** at [`0fd9646`][baseline]. The implemented baseline is Gmail API with `gmail.readonly`, **Implemented, disabled** and support status **None**. Its worker still keys messages by source and provider ID without a mailbox namespace, and it can miss late arrivals or a listing continuation. The other-mailboxes matrix row is **Not implemented**, support status **None**. [Gmail mapping][mapping] · [Integration matrix][matrix]

## Decision criteria

The same six criteria apply to each candidate. **2** means the reviewed sources give a clear fit for the named configuration, **1** means a conditional fit or unresolved work, and **0** means missing evidence or a material mismatch. Maintenance scores estimate the breadth of the test matrix. None measures runtime behavior. A protocol's reach cannot establish demand.

For this review, demand evidence means a public NextUp request identifying the account type, a concrete import workflow and why the manual or Gmail path is insufficient. Issue #25 records the general portability goal and had no comments on November 23, 2026. The reviewed repository issue list and public Discussions supplied no candidate-specific request meeting that definition. Private accounts and personal data were outside the review. [Issue #25][issue] · [Public issues][issues] · [Discussions][discussions]

| Criterion | Microsoft Graph | OAuth-capable IMAP | JMAP for Mail |
| --- | --- | --- | --- |
| Demand for a named target | 0 · No qualifying request | 0 · No qualifying request | 0 · No qualifying request |
| Actual credential breadth | 2 · Delegated mail read | 0 · Both reviewed provider grants permit more | 1 · Fastmail’s manual token and distributed OAuth have different rights |
| Setup for a non-technical user | 1 · Register a client, consent, handle tenant policy | 1 · Provider-specific registration, consent and server settings | 1 · Provider registration or manual token setup on an eligible plan |
| Identity, sync and failure recovery | 1 · Immutable IDs and per-folder delta, with archive and reset cases | 1 · Folder-scoped UIDs and validity resets complicate replay | 2 · Account-scoped IDs and explicit changes, destruction and state-loss signals |
| Documented account coverage | 2 · Personal Outlook and cloud Exchange explicitly documented | 1 · Two cloud services documented, other servers need individual review | 1 · One named deployment reviewed |
| Ongoing maintenance and testing | 1 · One API, separate account/consent and folder-transition cases | 0 · Multiple OAuth policies, server capabilities and identifier behaviors | 1 · One reference service, plus capability, token and resync cases |

## Candidate evidence

All provider and standards sources below were reviewed on **November 23, 2026**. Coverage describes the provider documentation. NextUp has validated none of these configurations.

**Microsoft Graph.** Evaluate Outlook.com personal accounts separately from Microsoft 365 work or school accounts with Exchange Online. Microsoft discontinued the hybrid REST path to on-premises Exchange mailboxes in July 2023. For import including message bodies, delegated `Mail.Read` reads the signed-in user's mailbox, including mail outside the local import filter. `Mail.ReadBasic` omits bodies. Sending and writing require other permissions. Registration, redirect and consent use Microsoft's identity platform. Tenant consent policy can require administrative approval. A background connector would use Microsoft’s token endpoint for refresh and Microsoft Graph for mail requests. [Permissions][graph-permissions] · [Get message][graph-get] · [Delegated authorization][graph-auth] · [Consent policies][ms-consent] · [On-premises boundary][hybrid]

Graph message IDs can change on a move. The immutable-ID preference preserves an ID across folders within a mailbox, with exceptions for an archive mailbox or export and reimport. A tracker needs per-folder paging and delta links. Apply changes to local storage before committing progress. A removal from a tracked folder must preserve the imported record. Test overlapping folders, a move, revoked consent and delta state requiring a new sync. [Immutable IDs][graph-id] · [Folder delta][graph-delta] · [Delta resets][delta-reset]

**OAuth-capable IMAP.** Gmail user OAuth for IMAP requests `https://mail.google.com/`, which can read, send, modify and delete mail. It broadens the existing Gmail grant without adding an independent provider. Microsoft documents `IMAP.AccessAsUser.All` for Microsoft 365 and Outlook.com and a separate SMTP permission. IMAP itself permits mailbox changes. Read-only operation using `EXAMINE` and `BODY.PEEK` prevents a client fetch from marking mail read, but cannot narrow the grant. The Microsoft cloud instructions do not establish OAuth availability for a particular on-premises Exchange server. A connector must identify the operator's OAuth issuer, permitted scopes and TLS mail server for each target. [Google IMAP OAuth][google-imap] · [Gmail scopes][gmail-scopes] · [Microsoft IMAP OAuth][ms-imap] · [IMAP4rev2][imap]

Sequence numbers can change after an expunge. A UID is meaningful within a folder and its UIDVALIDITY epoch. Store bounded scan progress per folder, rescan on validity change and retain local rows when the server removes a message. A move or copy can produce a different folder/UID identity. The optional OBJECTID extension supplies additional identifiers where advertised. Proving reconnect identity and avoiding duplicate moves across heterogeneous servers are significant test costs. [IMAP4rev2][imap] · [OBJECTID extension][imap-id]

**JMAP for Mail.** Fastmail is the named example. Its distributed OAuth route requires client registration and consent. Core plus mail scope grants read and management access. Submission uses a separate scope. For personal development, Fastmail separately offers a revocable JMAP API token with a read-only setting. The help page describes that setting as reading user data and does not promise a mail-only data boundary. API tokens are unavailable on Basic plans. Manual token creation adds setup burden. Neither route establishes JMAP availability for Gmail, Outlook.com, Microsoft 365 or on-premises Exchange. The Fastmail case uses Fastmail's authorization/token service for OAuth and its JMAP Session resource to discover the API destination. [Fastmail developer documentation][fastmail] · [Fastmail API token permissions][fastmail-token]

JMAP Session identifies accounts and capabilities. Within the selected account, `Email/query` lists IDs, `Email/get` fetches selected fields, and `Email/changes` reports created, updated and destroyed IDs. A message can belong to multiple folders under the same Email ID. Follow paged changes, rescan when the server returns `cannotCalculateChanges`, and keep local rows and user edits after destruction. Test reconnect to the same account, ambiguity after an account change, and provider-specific limits. [JMAP Core][jmap-core] · [JMAP for Mail][jmap-mail]

## Decision

For all three candidates, a prospective adapter would keep refresh tokens or revocable API tokens encrypted on the NextUp server with a separate restricted key. No NextUp credential was created or stored for this review. Exclude password-only configurations. During setup and sync, provider requests go only to that provider's identified authorization and mail services. Bounded message data flows to local records, with no mailbox writes or other processor. Reconnect must prove the same mailbox before reusing its namespace. Retain ambiguous legacy rows and leave ambiguous classifier hints unapplied. Preserve the user's edits, links and detection on retries, disconnect and provider changes. These are implementation requirements. This evaluation used public documents only and ran no protocol, live-account or conformance tests. [Contract][contract] · [Credential storage precedent][storage]

**Defer implementation.** Revisit the decision when a named account and workflow meet the demand criterion, the narrowest usable grant and setup burden are documented for that target, and there is a plan to isolate its records and checkpoints from Gmail. The accepted contract already specifies a synthetic conformance suite for these cases. The shared implementation decomposition is still a draft. Any implementation issue requires separate maintainer approval. [Required tests][tests] · [Implementation decomposition][decomposition] · [Issue #25][issue]

[baseline]: https://github.com/westondunn/nextup-get-hired/commit/0fd96465895156f7df4e2be7c4644ea5c439a8c1
[issue]: https://github.com/westondunn/nextup-get-hired/issues/25
[issues]: https://github.com/westondunn/nextup-get-hired/issues?q=is%3Aissue
[discussions]: https://github.com/westondunn/nextup-get-hired/discussions
[contract]: CORRESPONDENCE_CAPABILITY.md
[mapping]: CORRESPONDENCE_CAPABILITY.md#gmail-mapping
[tests]: CORRESPONDENCE_CAPABILITY.md#required-synthetic-adapter-tests
[matrix]: INTEGRATIONS.md#current-state
[decomposition]: planning/issue-drafts/correspondence-implementation-decomposition.md
[storage]: decisions/0003-google-connection.md
[graph-permissions]: https://learn.microsoft.com/en-us/graph/permissions-reference#mailread
[graph-get]: https://learn.microsoft.com/en-us/graph/api/message-get?view=graph-rest-1.0
[graph-auth]: https://learn.microsoft.com/en-us/graph/auth-v2-user
[ms-consent]: https://learn.microsoft.com/en-us/entra/identity-platform/permissions-consent-overview
[hybrid]: https://learn.microsoft.com/en-us/graph/hybrid-rest-support
[graph-id]: https://learn.microsoft.com/en-us/graph/outlook-immutable-id
[graph-delta]: https://learn.microsoft.com/en-us/graph/delta-query-messages
[delta-reset]: https://learn.microsoft.com/en-us/graph/delta-query-overview
[google-imap]: https://developers.google.com/workspace/gmail/imap/xoauth2-protocol
[gmail-scopes]: https://developers.google.com/workspace/gmail/api/auth/scopes
[ms-imap]: https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth
[imap]: https://datatracker.ietf.org/doc/html/rfc9051
[imap-id]: https://datatracker.ietf.org/doc/html/rfc8474
[fastmail]: https://www.fastmail.com/dev/
[fastmail-token]: https://www.fastmail.help/hc/en-us/articles/5254602856719-API-tokens
[jmap-core]: https://datatracker.ietf.org/doc/html/rfc8620
[jmap-mail]: https://datatracker.ietf.org/doc/html/rfc8621
