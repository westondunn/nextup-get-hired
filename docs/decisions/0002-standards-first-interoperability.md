# 0002 — Standards-first interoperability

- **Status of the direction:** Agreed by the maintainer on 2026-11-13.
- **Status of every technical choice below:** Proposed or undecided. Nothing here is implemented, scheduled or supported.
- **Date:** 2026-11-13, written against commit `81ac008`.
- **Tracking:** [#23](https://github.com/westondunn/nextup-get-hired/issues/23); part of [#3](https://github.com/westondunn/nextup-get-hired/issues/3).

## Context

NextUp is a self-hosted, single-user job-search workspace. Its integrations were written for one person's setup: the only correspondence adapters talk to Google, they are switched off in every shipped configuration, and earlier planning named specific tools for workflows and AI.

That does not serve someone who uses a different mailbox, does not want to pay for a particular AI subscription, or cannot reproduce the maintainer's environment. It also risks describing something as supported because a protocol name appears in the documentation.

At commit `81ac008` there is no code for IMAP, SMTP, CalDAV, iCalendar, any AI provider, MCP or a workflow tool, and no first-run onboarding. The current state of each integration is in [INTEGRATIONS.md](../INTEGRATIONS.md).

## The direction

For users: **your job search, with your choice of tools.**

For engineering: **open standards where available, documented API compatibility where needed, and clearly tested support.**

In practice:

1. **The core stands alone.** The workspace is useful with no email connection, no AI credential and no optional tooling. Integrations and AI assistance are enhancements.
2. **Standards first, not standards only.** A provider's own API is the right choice where it gives narrower permissions, more reliable synchronization, or something a generic protocol cannot do well.
3. **Flexibility without promising universality.** NextUp aims to let users choose providers. It does not claim to work with every provider, server or model.
4. **Support is evidence.** A capability is described as supported only when it has been validated for a named configuration and NextUp version. A protocol name, a passing unit test or a successful connection is not that evidence.
5. **Onboarding asks for as little as possible.** Setup should not require infrastructure knowledge or a long list of configuration decisions.
6. **Changing provider keeps the user's work.** Authoritative records, user edits and approved content survive a disconnect or a switch. Switching provider never moves existing data to the new processor automatically.
7. **Reading mail is not permission to process it elsewhere.** Consent to connect a mailbox does not authorize sending its content to an AI provider. That is a separate, explicit choice.
8. **Three separate things are validated separately:** that a connection works, that the feature behaves correctly, and that AI output is good enough.

## Distinctions this record commits to keeping

These are how NextUp will describe things. They are not commitments to build every item.

### Email

- Reading mail (IMAP, [RFC 9051][rfc9051]) and submitting mail (SMTP submission, [RFC 6409][rfc6409]) are separate capabilities. Importing correspondence does not require NextUp to send anything.
- Read-only behavior in the application is not the same as a read-only credential. IMAP itself includes commands that change a mailbox, so an IMAP credential generally permits more than reading. Google's documentation gives `https://mail.google.com/` as the scope for IMAP, POP and SMTP access, while the Gmail API offers the narrower `gmail.readonly` ([Gmail IMAP and OAuth][google-xoauth2], [Gmail API scopes][google-scopes]).
- Authentication differs by provider. Microsoft's documentation says Basic authentication is disabled in Exchange Online, that OAuth for IMAP, POP and SMTP is available for Microsoft 365 and Outlook.com users, and that reading and sending use different permission scopes ([deprecation of Basic authentication][ms-basic], [OAuth for IMAP, POP and SMTP][ms-oauth]).
- Gmail, Outlook.com, Microsoft 365 and on-premises Exchange are different support targets. The documentation reviewed here does not cover on-premises Exchange, and it has not been evaluated.

### Calendars

- iCalendar ([RFC 5545][rfc5545]) is a data format. Importing or exporting a file is not continuous synchronization.
- CalDAV ([RFC 4791][rfc4791]) and provider calendar APIs are possible adapter approaches.
- Calendar authorization is its own grant. It is never inferred from an email connection.

### AI

- Five things are kept apart: the provider, how access is authenticated, what the user is billed for, which API the endpoint is compatible with, and how good the output is for a task.
- An "OpenAI-compatible" endpoint is a documented compatibility target, not a guarantee of identical behavior. As one example, Ollama's documentation says it "supports a subset of the OpenAI API" and lists unsupported parameters ([Ollama OpenAI compatibility][ollama-openai]).
- Access through a consumer subscription is in scope only where the provider authorizes a mechanism for it and NextUp has implemented and validated that mechanism.
- Local inference is optional. Hardware needs and performance limits are stated, and are unknown until measured.
- An endpoint on `localhost` does not by itself show that inference or data processing stays on the machine.
- There is no silent fallback to cloud processing, to another provider, or to a separately billed service.

### Workflow and assistant access

- A versioned NextUp API is a possible stable boundary for other tools.
- An [OpenAPI][openapi] description documents an interface. It does not establish who is authorized or what a workflow means.
- MCP describes itself as "an open-source standard for connecting AI applications to external systems" ([MCP introduction][mcp-intro]). It is a possible future way for assistants to reach NextUp. It is not an inference API, a route to subscription access, or application authorization.
- No MCP server, plugin platform or orchestration layer will be added only to be able to claim standards support.

## Not decided

| Question | Where it is decided |
| --- | --- |
| The contract every read-only correspondence adapter must meet | [#24](https://github.com/westondunn/nextup-get-hired/issues/24) |
| Whether to build a second email adapter, and which | [#25](https://github.com/westondunn/nextup-get-hired/issues/25) |
| Who owns the Google OAuth registration, and the flow and token storage | [#9](https://github.com/westondunn/nextup-get-hired/issues/9) |
| Registration ownership for providers other than Google | Not tracked; decided per provider when one is proposed |
| The first AI task, its contract, and the first API compatibility target | [#26](https://github.com/westondunn/nextup-get-hired/issues/26) |
| Evidence required for each support status, and how often it is re-validated | [#27](https://github.com/westondunn/nextup-get-hired/issues/27) |
| The guided setup path, packaging approach and first platforms | [#28](https://github.com/westondunn/nextup-get-hired/issues/28) |
| A versioned public API | Not tracked; deferred |
| Sending mail, wider calendar synchronization, more providers, MCP access, workflow tooling, advanced automation | Not tracked; deferred or discovery work listed in the [roadmap](../ROADMAP.md) |
| Where the new outcomes sit relative to existing priorities | Planning; not decided here |

## Alternatives and tradeoffs

| Choice | One side | Other side | Position |
| --- | --- | --- | --- |
| Standards-only or standards-first | Standards-only gives one adapter per protocol and the widest nominal reach, but forces the broadest credential where a provider offers a narrower one, and inherits each server's quirks | Standards-first allows a provider API where it is safer or more reliable, at the cost of more adapters | Standards-first (agreed) |
| Provider APIs or generic protocols | Provider APIs can offer narrow scopes, stable identifiers and incremental sync, but each needs its own registration, tests and upkeep | Generic protocols reach more servers with one adapter, but permissions are coarser and behavior varies by server | Decided per capability, on evidence ([#25](https://github.com/westondunn/nextup-get-hired/issues/25)) |
| User-owned or project-managed OAuth registration | User-owned keeps the project out of the credential path and needs no provider verification by the project, but setup is hard for non-developers. Google issues 7-day refresh tokens to external-user projects in "Testing" status ([Google OAuth 2.0][google-oauth]) | Project-managed makes setup simple, but the project must pass provider verification (Google requires restricted-scope verification for `gmail.readonly`, and a security assessment if restricted data is stored on or sent through servers), becomes responsible for a shared client, and is a single point of failure | Undecided ([#9](https://github.com/westondunn/nextup-get-hired/issues/9)) |
| Guided setup or advanced configuration | Guided setup lowers the barrier but hides choices and needs validating with real users | Advanced configuration is explicit and flexible but excludes most non-developers | Guided by default, advanced available; the design is open ([#28](https://github.com/westondunn/nextup-get-hired/issues/28)) |
| Provider flexibility or support scope | Each added provider or profile adds permanent test and maintenance cost | Too few leaves users without a path | A small tested set, with an explicit status for untested custom connections ([#27](https://github.com/westondunn/nextup-get-hired/issues/27)) |

## Boundaries that do not change

- Application rules and authoritative records stay in NextUp. No optional tool, cloud account or model provider becomes a hidden dependency of the core.
- The external classifier contract in [CORRESPONDENCE_SYNC.md](../CORRESPONDENCE_SYNC.md) is unchanged, including its stored key and role names. No pinned migration is edited.
- Email, job descriptions, attachments and model output are untrusted input.
- Outbound communication and consequential actions need explicit review. A provider failure never disables the manual workflow or overwrites a user decision.
- Deployment identity checks, file-based secrets, database role separation, pinned migration lineage and isolated verification stay as they are.
- Google account authorization and the request checks from [decision 0001](0001-local-session-boundary.md) are not authentication to NextUp.

## Claims NextUp does not make

- That any AI subscription works.
- That it works with every email provider.
- That it is fully local while an enabled integration sends data elsewhere.
- That it is production-ready, secure or supported, without evidence for the specific claim.
- That setup is one click, before representative users have validated that.

## Sources

Reviewed on 2026-11-13. Provider policies change; re-check before relying on any of these.

- [Gmail API scopes][google-scopes] — classifies `gmail.readonly`, `gmail.metadata`, `gmail.modify` and `https://mail.google.com/` as restricted; restricted scopes require restricted-scope verification, and a security assessment if restricted data is stored on or transmitted through servers.
- [Using OAuth 2.0 to access Google APIs][google-oauth] — refresh-token expiry, including 7 days for external-user projects in "Testing" status.
- [Gmail IMAP, POP and SMTP with OAuth][google-xoauth2] — the scope for IMAP, POP and SMTP access.
- [Deprecation of Basic authentication in Exchange Online][ms-basic] — article dated 2026-07-10.
- [Authenticate an IMAP, POP or SMTP connection using OAuth][ms-oauth] — scopes `IMAP.AccessAsUser.All`, `POP.AccessAsUser.All`, `SMTP.Send`; availability for Microsoft 365 and Outlook.com.
- [Ollama: OpenAI compatibility][ollama-openai] — an example of partial API compatibility.
- [Model Context Protocol: introduction][mcp-intro].
- [OpenAPI Specification][openapi].
- RFCs: [9051 IMAP4rev2][rfc9051], [6409 Message Submission][rfc6409], [5545 iCalendar][rfc5545], [4791 CalDAV][rfc4791], [6749 OAuth 2.0](https://www.rfc-editor.org/rfc/rfc6749), [7636 PKCE](https://www.rfc-editor.org/rfc/rfc7636), [8252 OAuth 2.0 for Native Apps](https://www.rfc-editor.org/rfc/rfc8252).

[google-scopes]: https://developers.google.com/workspace/gmail/api/auth/scopes
[google-oauth]: https://developers.google.com/identity/protocols/oauth2
[google-xoauth2]: https://developers.google.com/workspace/gmail/imap/xoauth2-protocol
[ms-basic]: https://learn.microsoft.com/en-us/exchange/clients-and-mobile-in-exchange-online/deprecation-of-basic-authentication-exchange-online
[ms-oauth]: https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth
[ollama-openai]: https://github.com/ollama/ollama/blob/main/docs/api/openai-compatibility.mdx
[mcp-intro]: https://modelcontextprotocol.io/docs/getting-started/intro
[openapi]: https://spec.openapis.org/oas/latest.html
[rfc9051]: https://www.rfc-editor.org/rfc/rfc9051
[rfc6409]: https://www.rfc-editor.org/rfc/rfc6409
[rfc5545]: https://www.rfc-editor.org/rfc/rfc5545
[rfc4791]: https://www.rfc-editor.org/rfc/rfc4791
