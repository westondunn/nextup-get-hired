# 0003 — Google connection: client registration, flow and token storage

- **Status:** Accepted by the maintainer on 2026-11-14. Nothing described here is implemented.
- **Date:** 2026-11-14, written against commit `c5e1773`.
- **Tracking:** decision [#9](https://github.com/westondunn/nextup-get-hired/issues/9); implementation [#10](https://github.com/westondunn/nextup-get-hired/issues/10), [#11](https://github.com/westondunn/nextup-get-hired/issues/11), [#12](https://github.com/westondunn/nextup-get-hired/issues/12); validation [#14](https://github.com/westondunn/nextup-get-hired/issues/14); part of [#3](https://github.com/westondunn/nextup-get-hired/issues/3).

Every statement about Google's behavior cites a page in [Sources](#sources), all read on 2026-11-14. No live Google account was used; see [Not verified](#not-verified).

## Context

NextUp can read Gmail and Google Calendar, read-only, but only with a refresh token placed in configuration by hand (`backend/app/sources/gmail.py`, `google_calendar.py`). There is no consent screen, no stored token, no way to see what was granted, and no way to revoke. Both adapters are switched off in every shipped configuration, and the launcher refuses any other value for the two sync flags (`scripts/oss_env.py`).

This record decides how a user connects a Google account through the browser. It follows [decision 0001](0001-local-session-boundary.md) for the local session and [decision 0002](0002-standards-first-interoperability.md) for how capabilities and support are described.

Connecting a Google account authorizes NextUp to read from Google. It is not a login to NextUp and does not protect the API.

## Decided by the maintainer

| Question | Decision |
| --- | --- |
| Who owns the OAuth client registration | **The user.** Each user creates an OAuth client in their own Google Cloud project. The project ships no shared client |
| Which client type the user creates | **Web application** |
| Where the user supplies the client ID and client secret | **In Settings**, under the local session. They are stored encrypted with the tokens and never shown again |
| What happens to the refresh token supplied through configuration | **It stays as a fallback.** A stored connection takes precedence when one exists |

## Decision

### 1. The user's registration

The user creates a Google Cloud project, enables the Gmail API and the Google Calendar API, configures the consent screen, and creates one OAuth client of type "Web application". The steps become a setup guide in [#14](https://github.com/westondunn/nextup-get-hired/issues/14); this record fixes only what the guide must say.

What Google's rules mean for a user-owned registration:

| Audience setting | Consequence | Source |
| --- | --- | --- |
| External, publishing status "Testing" | Only listed test users can authorize. Google states: "Authorizations by a test user will expire seven days from the time of consent." The user reconnects every week | [App audience][g-audience], [OAuth 2.0][g-oauth] |
| External, "In production", not verified | No seven-day expiry. Google shows an "unverified app" warning, and the project is limited to 100 new users over its lifetime. Google lists an app "for your personal use (fewer than 100 users)" as not needing verification | [App audience][g-audience], [Verification not needed][g-noverify] |
| Internal (a project owned by a Google Workspace or Cloud Identity organization) | Only that organization's users can authorize. No unverified warning and no user cap | [App audience][g-audience], [Verification not needed][g-noverify] |

The guide will describe all three and say which consequence each has. It will not present "Testing" as the normal choice, because of the weekly reconnection.

The user is the developer of their own project. Google states that all apps using its APIs must comply with its API Services User Data Policy whether or not they are verified ([Verification not needed][g-noverify]). The guide must say so.

### 2. Client and redirect address

Google requires the redirect address in a request to "exactly match one of the authorized redirect URIs" registered for a Web application client, including scheme, case and trailing slash. Addresses must use HTTPS, with one exception: "Localhost URIs (including localhost IP address URIs) are exempt from this rule." ([Web server flow][g-web])

- The callback path is fixed: `/api/google/callback`.
- The user registers the address for each way they open NextUp. With the default development port these are `http://127.0.0.1:15173/api/google/callback` and `http://localhost:15173/api/google/callback`.
- NextUp builds the redirect address from the `Host` header of the request that starts the flow. That header has already passed the fixed host allowlist from decision 0001, so only `localhost` or `127.0.0.1` can appear. The same address is sent again at the token exchange.
- An address that is not registered fails at Google with `redirect_uri_mismatch`, before anything reaches NextUp. Settings shows the exact address to register.

### 3. Starting the flow

`POST` to a start route. It requires the local session and passes the cross-origin check like every state-changing route. It creates:

- a random `state` value of at least 128 bits;
- a PKCE verifier and its `S256` challenge ([RFC 7636][rfc7636]);
- a random browser-binding value, set as a cookie that is `HttpOnly`, `SameSite=Lax`, limited to the callback path, and valid for ten minutes.

The verifier, the redirect address, the capabilities asked for and a hash of the binding value are kept in Redis under a hash of `state`, for ten minutes, for one use.

The authorization request goes to the endpoint in Google's discovery document with these parameters ([Web server flow][g-web], [discovery document][g-discovery]):

| Parameter | Value | Why |
| --- | --- | --- |
| `response_type` | `code` | Authorization-code flow; the exchange happens on the server |
| `scope` | Only the scopes of the capabilities the user selected | See section 5 |
| `access_type` | `offline` | Sync runs when the user is not present |
| `prompt` | `consent` | Google returns a refresh token only on the first exchange unless consent is prompted again |
| `include_granted_scopes` | `true` | Adding a capability later keeps the one already granted |
| `state` | The value above | Google describes it as a defence against cross-site request forgery, to be verified by the application |
| `code_challenge`, `code_challenge_method` | The challenge, `S256` | The discovery document lists `S256` as supported |

### 4. The callback

`GET /api/google/callback` is the one connection route that cannot require the session cookie. The session cookie is `SameSite=Strict`, and a browser does not send such a cookie on a navigation that arrives from another site ([cookie standard draft][samesite]), which is exactly what Google's redirect is. This amends decision 0001, which said every Google connection route would require a session.

The callback is instead tied to the session that started the flow:

- `state` must match an unused, unexpired entry. The entry is deleted as it is read, so a replay finds nothing.
- The browser-binding cookie must be present and match the stored hash. A `SameSite=Lax` cookie is sent on a top-level navigation from another site that uses `GET`.
- Only a start request made with a valid session can create an entry.

If either check fails, the callback answers `400` with a fixed message, exchanges nothing and stores nothing.

If they pass, the server exchanges the code at Google's token endpoint with the client ID, the client secret, the verifier and the same redirect address. The browser never sees a token. The callback then answers with a redirect to a fixed address inside NextUp that carries one of a fixed set of result words and nothing else.

The authorization code arrives in the callback's query string. It is short-lived and useless without the verifier and the client secret, but it must still not be recorded:

- the callback's query string must not reach any log. The API server's access log is on by default and records request lines, so the implementation has to keep this route's query string out of it and show that with a test;
- the response sends `Referrer-Policy: no-referrer`.

### 5. Capabilities and scopes

| Capability | Scope requested | What the credential permits | What NextUp does with it |
| --- | --- | --- | --- |
| Correspondence: read | `https://www.googleapis.com/auth/gmail.readonly` | Reading all mail and mail settings in the account | Reads messages matching the configured query |
| Calendar: read | `https://www.googleapis.com/auth/calendar.readonly` | Reading every calendar the account can see | Reads events from the primary calendar inside the sync window |

- The user chooses mail, calendar or both when connecting. One is never requested because the other was.
- Google lets the user grant only some of what is requested, and says applications "can't assume users grant all requested scopes" and should "handle any denial of scopes by disabling relevant features" ([Granular permissions][g-granular]). NextUp reads the `scope` field of the token response and treats only the capabilities actually granted as available.
- Settings shows two things separately: what Google granted, and what NextUp is set to use. Switching a capability off in NextUp stops NextUp using it; it does not reduce what the credential permits.
- Google's revocation "removes all OAuth 2.0 scopes previously granted to a project" ([Web server flow][g-web]). There is no way to revoke one capability. To narrow a grant the user disconnects and connects again with fewer capabilities.
- No identity scope is added. The connected account's address is read through an API the grant already covers.

Google's reference lists `calendar.events.readonly` among the scopes that authorize the request NextUp makes ([Events: list][g-events-list]). It is narrower than `calendar.readonly`. Changing to it is a possible later step and is not decided here.

### 6. Storage

One connection, in a new table added by a new migration revision through the guard. No pinned revision is touched.

| Stored | Form |
| --- | --- |
| Client secret, refresh token | Encrypted |
| Client ID, granted scopes, account address, connection state, timestamps | Plain |
| Access token | Not stored; obtained when needed |

- Encryption is authenticated encryption from a maintained library, which is a new backend dependency. Each record carries a key version.
- The key is a secret file generated by the launcher, like the database passwords. It is mounted into the `api` and `worker` services only, read from a file only, and never accepted as an inline value.
- Losing or replacing the key makes the stored connection unreadable. The user connects again. Key rotation without reconnecting is not part of the first version.
- This protects a copy of the database, a backup or a volume taken without the key. It does not protect against a process running as the user's own operating-system account, which can read the key file. Decision 0001 says the same of the setup code.
- No token, secret, code, verifier or `state` value appears in a response body, a log line, an error message or a fixture.

### 7. Use, refresh and concurrency

- A sync obtains an access token from the stored refresh token, as the adapters do today, and checks that the grant includes the capability's scope before using it.
- Two workers may refresh at the same moment. Each receives its own access token, and nothing stored changes. If a refresh response ever includes a new refresh token, it replaces the stored one under a row lock.
- Changes to the connection (connect, reauthorize, disconnect, marking it as needing reauthorization) take the same row lock.
- A refused refresh is not retried in a loop. See the table below.

### 8. Disconnect

Disconnect sends the refresh token to Google's revocation endpoint and then deletes the stored credentials. The credentials are deleted even if the revocation request fails; the user is told that access may still be listed in their Google Account and can be removed there.

Imported messages, events, links and user edits are kept. Sync for both capabilities stops.

### 9. Configuration

**Stays as it is:**

- Legacy unprefixed names are refused.
- The two sync flags remain the outer switch for the installation and default to off. The connection routes refuse with a fixed message when the flag for a requested capability is off.
- Staging refuses integrations and their credentials (`NXG-C09`). The connection routes refuse in staging.
- In fixture data mode every live provider path refuses, the connection routes included. They call `require_live_requests` first.
- The three Google configuration secrets are still read. Together they are the fallback path.

**Needs a reviewed change, each with tests, in the issue that implements it:**

| Rule today | Change | Safety rationale |
| --- | --- | --- |
| `NXG-C08`: a sync flag that is on requires all three Google secrets in configuration | With a flag on, configuration must hold all three or none. One or two is still refused | The rule exists so that a half-configured integration cannot start. With stored credentials, "none" is valid: nothing is sent to Google until a connection exists, and sync reports that it is not connected |
| The launcher accepts only `false` for the sync flags | A documented, explicit way to turn a flag on in the development environment | Without it the connection can be exercised only in tests. This is part of validating the setup ([#14](https://github.com/westondunn/nextup-get-hired/issues/14)); the shipped default stays off |
| Enabling sync in Settings requires the flag and the three configuration secrets | It requires the flag and either a stored connection that grants the capability or the complete fallback | Same condition, moved to where the credential now lives |

**Fallback precedence.** A stored connection is always used when one exists. The configuration token is used only when there is no stored connection and all three secrets are present. Settings shows that state as configured outside NextUp: no consent record, no per-capability record and no disconnect.

## Failure behavior

Every row leaves the application usable without Google, and none changes an imported record or a user edit.

| Situation | What happens |
| --- | --- |
| The user declines at Google | Nothing is stored. An existing connection is left as it was |
| Google returns any other error to the callback | The same. Google's error text is not shown or logged; the user sees a fixed message |
| Unknown, expired or replayed `state`, or the binding cookie is missing or wrong | `400`, fixed message. No exchange, nothing stored |
| The token exchange fails, or returns no refresh token | Nothing is stored. The code is not retried |
| The user grants none of the capabilities asked for | The returned token is revoked. Nothing is stored |
| The user grants some of them | The connection is stored. Only the granted capabilities are available, and Settings says which were not granted |
| A sync finds the grant lacks its scope | That capability reports it and does nothing. The other is unaffected |
| A refresh is refused as invalid | The connection is marked as needing reauthorization and both capabilities stop until the user reauthorizes. Google's documented causes include the user revoking access, six months without use, a password change when the token has Gmail scopes, the seven-day limit in "Testing", and exceeding 100 refresh tokens for one account and client ([OAuth 2.0][g-oauth]) |
| Google is unreachable or returns a temporary error | The existing sync statuses apply. The connection state does not change |
| An administrator has restricted the service | Reported as needing attention, with a fixed message |
| The key file is missing or the record cannot be decrypted | The connection is reported as unreadable. Sync does nothing. The rest of the application is unaffected |
| Two connect flows run at once | Each `state` works once. The flow that completes last is the stored connection |
| The user connects a different Google account | The earlier grant is revoked first, then replaced. Records imported from the earlier account stay |

## What leaves the machine

| Destination | What is sent | By |
| --- | --- | --- |
| Google's authorization endpoint | Client ID, redirect address, scopes, `state`, PKCE challenge | The user's browser |
| Google's token and revocation endpoints | Authorization code, client ID, client secret, PKCE verifier, refresh token | The `api` and `worker` services |
| Gmail and Calendar APIs | Read requests with an access token | The `worker` service |

Nothing is sent to the NextUp project or to any other party. Data flows from Google to the local installation only.

## Alternatives considered

| Alternative | Why not |
| --- | --- |
| A project-managed shared client | The project would have to pass Google's restricted-scope verification for `gmail.readonly`, hold a shared client and become a single point of failure. See decision 0002 |
| A "Desktop app" client | It needs no registered redirect address and Google documents PKCE for it, but Google's desktop guide says incremental authorization is not available for installed apps, and describes them as public clients that "cannot keep secrets confidential" ([Desktop flow][g-desktop]). The maintainer chose Web application |
| Client credentials in configuration files | The user would have to create files and restart the stack. Decision 0002 asks setup to need as little as possible |
| Retiring the configuration refresh token | It would leave one credential path, but would break any installation that uses it today. The maintainer chose to keep it |
| Requiring the session cookie on the callback | Not possible with a `SameSite=Strict` cookie. Relaxing the session cookie to `Lax` for every route would weaken it everywhere to serve one route |
| Storing tokens unencrypted | A database copy or backup would then hold a working credential for the user's mailbox |

## What this does not change

- Ports stay on the loopback interface. The API still has no authentication.
- No scope beyond read-only mail and read-only calendar. No Google Docs or Drive.
- NextUp's own detection stays authoritative, and the classifier contract in [CORRESPONDENCE_SYNC.md](../CORRESPONDENCE_SYNC.md) is unchanged.
- Nothing here makes the Google connection supported. That needs the validation in [#14](https://github.com/westondunn/nextup-get-hired/issues/14) and a complete profile in [INTEGRATIONS.md](../INTEGRATIONS.md).

## Implementation slices

1. **Connect** ([#10](https://github.com/westondunn/nextup-get-hired/issues/10)): the key secret in the launcher and Compose validation, the migration, saving client credentials, the start and callback routes, the `NXG-C08` change, and stored credentials reaching the adapters. Mocked provider calls only.
2. **Manage** ([#11](https://github.com/westondunn/nextup-get-hired/issues/11)): status, test, reauthorize, disconnect with revocation, and the needs-reauthorization state.
3. **Settings** ([#12](https://github.com/westondunn/nextup-get-hired/issues/12)): the redirect addresses to register, granted and used capabilities shown separately, actionable errors, accessibility coverage.
4. **Validate** ([#14](https://github.com/westondunn/nextup-get-hired/issues/14)): the setup guide, the explicit way to switch a flag on, and a clean-machine run. A live-account test needs separate approval.

The all-day event work ([#38](https://github.com/westondunn/nextup-get-hired/issues/38)) also adds a migration. Whichever lands first is the first revision after the pinned history.

## Decisions on the questions raised in review

The maintainer accepted the recommended answer to each on 2026-11-14.

| Question | Decision |
| --- | --- |
| A partial grant | It is stored, and only the capabilities actually granted are offered, as section 5 describes. The earlier criterion in [#10](https://github.com/westondunn/nextup-get-hired/issues/10), that partial consent stores nothing, was replaced on the same day |
| The callback and the session cookie | The callback is exempt from the session cookie and is protected by the `state` and binding-cookie checks in section 4. Decision 0001 records the exception |
| Status and test routes | They require the session, like the other connection routes |
| The guide's stance on the consent-screen audience | It describes all three settings and does not present "Testing" as the normal choice |
| The encryption key | It is mounted into `api` and `worker` only. There is no rotation in the first version |

## Not verified

- **No live Google account was used.** Everything here is read from documentation.
- **PKCE with a Web application client.** Google's web-server guide does not mention it. Its discovery document lists `S256`, and its desktop guide documents the parameters. Whether Google refuses a wrong verifier for a Web application client can only be shown with a live account. NextUp's own handling is testable with mocked calls.
- **How the unverified-app warning reads today,** and whether a personal Google account can continue past it without extra steps.
- **Whether a refresh response can carry a new refresh token.** Section 7 handles both cases.
- **Scope classification of `calendar.readonly`.** The Calendar page read for this record does not state one. `gmail.readonly` is restricted; see the sources in decision 0002.

## Sources

Read on 2026-11-14. Google changes these pages; re-check before relying on any of them.

- [Using OAuth 2.0 for Web Server Applications][g-web] — redirect address rules, request parameters, incremental authorization, token revocation.
- [OAuth 2.0 for iOS & Desktop Apps][g-desktop] — the desktop flow, for the alternative considered, and PKCE parameters.
- [Using OAuth 2.0 to Access Google APIs][g-oauth] — refresh-token expiry and limits.
- [How to handle granular permissions][g-granular] — partial grants.
- [Google's OpenID Connect discovery document][g-discovery] — endpoints and supported PKCE methods.
- [Manage App Audience][g-audience] — user types, publishing status, test users, the user cap.
- [When is verification not needed][g-noverify] — personal, internal and testing use.
- [Unverified apps][g-unverified] — when the warning is shown.
- [Calendar API: Events: list][g-events-list] — scopes that authorize the request.
- [Cookies: HTTP State Management Mechanism][samesite], draft 22 of 1 December 2025 — when `SameSite=Strict` and `SameSite=Lax` cookies are sent.
- Standards referenced and not re-read for this record: [RFC 6749][rfc6749] (OAuth 2.0), [RFC 7636][rfc7636] (PKCE).

[g-web]: https://developers.google.com/identity/protocols/oauth2/web-server
[g-desktop]: https://developers.google.com/identity/protocols/oauth2/native-app
[g-oauth]: https://developers.google.com/identity/protocols/oauth2
[g-granular]: https://developers.google.com/identity/protocols/oauth2/resources/granular-permissions
[g-discovery]: https://accounts.google.com/.well-known/openid-configuration
[g-audience]: https://support.google.com/cloud/answer/15549945
[g-noverify]: https://support.google.com/cloud/answer/13464323
[g-unverified]: https://support.google.com/cloud/answer/7454865
[g-events-list]: https://developers.google.com/workspace/calendar/api/v3/reference/events/list
[rfc6749]: https://www.rfc-editor.org/rfc/rfc6749
[rfc7636]: https://www.rfc-editor.org/rfc/rfc7636
[samesite]: https://datatracker.ietf.org/doc/html/draft-ietf-httpbis-rfc6265bis
