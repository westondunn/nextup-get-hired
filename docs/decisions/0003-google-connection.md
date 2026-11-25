# 0003 — Google connection: client registration, flow and token storage

- **Status:** Accepted by the maintainer on 2026-11-14. The [Google connect evidence](#google-connect-evidence) records the implementation and the 2026-11-23 clarification of refusal behavior.
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

**Amendment accepted November 24, 2026.** Disconnect deletes the saved OAuth client and grant, invalidates pending consent and pauses both syncs in one local transaction. Only after that commit may NextUp try to revoke the grant at Google. Imported messages, events, links and user edits survive. Reconnecting uses the existing consent flow. After disconnect, enabling eligible sync requires an explicit change to sync settings. A new grant starts with a bounded rescan. If an older import has the same provider ID and its mailbox cannot be verified, NextUp preserves that row. The lifecycle stores a cutoff for automatic updates to imports, separate from the grant and its per-capability success times.

Disconnect makes at most one remote attempt within five seconds. It skips that attempt when the installation disallows live access, the saved token cannot be opened, or a separately configured credential may share the grant. Only a confirmed provider response counts as revocation. A refusal, timeout or interrupted request can leave access listed at Google. The user can check or remove the grant under third-party connections in their Google Account. Removing a shared grant there can affect other credentials.

#### Lifecycle API and troubleshooting

In every shipped configuration both Google capabilities are switched off. The guarded enablement path and clean-machine setup are tracked in [#14](https://github.com/westondunn/nextup-get-hired/issues/14). In an eligible configuration, unlock the local session, save the registered client in Settings and start consent with the required read-only capabilities. The [Settings walkthrough](../DEVELOPMENT.md#google-connection-in-settings) describes testing, reauthorization, disconnect and recovery. The backend contract is:

| Local endpoint | Result |
| --- | --- |
| `GET /api/google/connection` or a successful `PUT /api/google/client` | The existing state, local client ID and account address, enabled and granted capabilities, plus `credential_source` and per-capability `sync`. Reading status uses only local data. |
| `POST /api/google/connection/test` | One refresh of the saved grant and a read-only probe for each enabled, granted capability. Returns `result: complete`, fixed codes in `capabilities.gmail` and `capabilities.calendar`, and the updated `connection`. Each probe can retry one temporary failure within the shared ten-second provider budget. Testing imports nothing and leaves sync timestamps alone. |
| `POST /api/google/connect` | Starts the same single-use browser consent flow for connecting or reauthorizing. A failed reconnect preserves the preceding grant. |
| `DELETE /api/google/connection` | Returns `disconnected` or `already_disconnected`, `revocation` (`confirmed`, `unconfirmed` or `not_applicable`), and the resulting `connection`. A repeat cannot confirm a prior attempt. A credential supplied only through configuration must be managed outside NextUp. Local cleanup is available even when Google access is disabled. |

A saved grant has source `stored` even when unreadable. A complete configuration fallback has source `configured` when no grant is saved. Otherwise the source is `none`. Each `sync.gmail` and `sync.calendar` reports `active`, `last_attempt_at`, `last_status`, `last_success_at` and `freshness`. An attributable, committed, complete pass can advance last success even when it imports zero records. Partial work, a failed attempt or a probe cannot advance it. Old grants and unverified fallback identities supply no freshness evidence. Freshness is `inactive` when sync is off, `unknown` before an attributable success, and `stale` when the last success is older than twice the configured interval. Otherwise it is `current`.

The test action reports one of `ok`, `disabled`, `not_granted`, `wrong_scope`, `needs_reauthorization`, `admin_restricted`, `temporarily_unavailable` or `provider_rejected` for each capability. A sync attempt uses `not_run`, `ok`, `disabled`, `not_configured`, `needs_reauthorization`, `wrong_scope`, `admin_restricted`, `temporarily_unavailable`, `unreadable`, `connection_error` or `provider_rejected`. Timestamps are nullable UTC values. Test and disconnect use an empty request body. An action refusal carries `detail.code` and a fixed `detail.message`. Local-session refusal keeps its existing HTTP 401 response. An unavailable action returns HTTP 409 and a local store failure returns HTTP 503.

Use fresh consent for a definite `needs_reauthorization` result. For `wrong_scope`, request the missing read-only capability. For `admin_restricted`, the account administrator controls access. On `temporarily_unavailable`, retry later. A `busy` action is safe to retry after the current action finishes. An unreadable local grant can still be disconnected. The two action routes return fixed reasons and exclude provider response bodies and credentials.

### 9. Configuration

**Stays as it is:**

- Legacy unprefixed names are refused.
- The two sync flags remain the outer switch for the installation and default to off. The connection routes refuse with a fixed message when the flag for a requested capability is off.
- Staging refuses integrations and their credentials (`NXG-C09`). Status and local cleanup remain available.
- In fixture data mode every live provider path refuses through `require_live_requests`. Status and local cleanup make no provider call.
- The three Google configuration secrets are still read. Together they are the fallback path.

**Configuration decisions and implementation status**

| Original rule | Decision and status | Safety rationale |
| --- | --- | --- |
| `NXG-C08`: a sync flag that is on requires all three Google secrets in configuration | Implemented. With a flag on, configuration must hold all three or none. One or two is still refused | The rule exists so that a half-configured integration cannot start. With stored credentials, "none" is valid: nothing is sent to Google until a connection exists, and sync reports that it is not connected |
| The launcher accepts only `false` for the sync flags | Pending. Provide a documented, explicit way to turn a flag on in the development environment | Without it the connection can be exercised only in tests. This is part of validating the setup ([#14](https://github.com/westondunn/nextup-get-hired/issues/14)); the shipped default stays off |
| Enabling sync in Settings requires the flag and the three configuration secrets | Implemented. It requires the flag and either a usable stored grant for that capability or the complete fallback when there is no stored grant | Same condition, moved to where the credential now lives |

**Fallback precedence.** A stored connection is always used when one exists. The configuration token is used only when there is no stored connection and all three secrets are present. Settings identifies the fallback as configured outside NextUp. If a client was also saved locally without a grant, Disconnect removes that client and pauses sync. The configured credential is managed outside NextUp. A fallback alone offers no Disconnect action.

## Failure behavior

Every row leaves the application usable without Google, and none changes an imported record or a user edit.

| Situation | What happens |
| --- | --- |
| The user declines at Google | Nothing is stored. An existing connection is left as it was |
| Google returns any other error to the callback | The same. Google's error text is not shown or logged; the user sees a fixed message |
| Unknown, expired or replayed `state`, or the binding cookie is missing or wrong | `400`, fixed message. No exchange, nothing stored |
| The token exchange fails, or returns no refresh token | Nothing is stored. The code is not retried |
| The user grants none of the capabilities asked for | The returned token is discarded and no new grant is stored. NextUp attempts revocation only if it holds neither a stored grant nor a complete configuration fallback. Any earlier connection stays intact |
| The user grants some of them | The connection is stored. Only the granted capabilities are available, and Settings says which were not granted |
| A sync finds the grant lacks its scope | That capability reports it and does nothing. The other is unaffected |
| A refresh is refused as invalid | The connection is marked as needing reauthorization and both capabilities stop until the user reauthorizes. Google's documented causes include the user revoking access, six months without use, a password change when the token has Gmail scopes, the seven-day limit in "Testing", and exceeding 100 refresh tokens for one account and client ([OAuth 2.0][g-oauth]) |
| Google is unreachable or returns a temporary error | The existing sync statuses apply. The connection state does not change |
| An administrator has restricted the service | Reported as needing attention, with a fixed message |
| The key file is missing or the record cannot be decrypted | The connection is reported as unreadable. Sync does nothing. The rest of the application is unaffected |
| Two connect flows run at once | Each `state` works once. The flow that completes last is the stored connection |
| The user connects a different Google account | The new grant is stored first. NextUp may then revoke the previous grant if its account is known and it is safe to do so. Imported records stay |

**Implementation notes, 2026-11-15 ([#10](https://github.com/westondunn/nextup-get-hired/issues/10)).** Two implementation choices narrowed the original wording. Google's revocation ends an account's whole grant to a client, so a revocation at the wrong moment can end a grant NextUp is using.

- **A different account.** The new grant is stored first. NextUp then attempts revocation of the earlier grant only if its account is known, differs from the replacement and no complete configuration fallback may share it. If storing fails, nothing has been revoked and the earlier connection still works. The row lock is not held while Google is contacted. When the same account connects again, nothing is revoked.
- **None of the capabilities asked for is granted.** Nothing is stored, as written. The returned token is discarded. NextUp attempts revocation only if it holds neither a stored grant nor a complete configuration fallback. Revoking shared access could invalidate the earlier connection. The maintainer confirmed this wording for #10 on 2026-11-23.

## Google connect evidence

Reviewed [main at `0fd9646`](https://github.com/westondunn/nextup-get-hired/commit/0fd96465895156f7df4e2be7c4644ea5c439a8c1) on 2026-11-23 against [#10](https://github.com/westondunn/nextup-get-hired/issues/10). Six merged pull requests delivered the connection path. [#51](https://github.com/westondunn/nextup-get-hired/pull/51) ([`ae1ed0c`](https://github.com/westondunn/nextup-get-hired/commit/ae1ed0c3f4e44233c0e4bc8d087892590f569602)) added credential encryption, [#52](https://github.com/westondunn/nextup-get-hired/pull/52) ([`0086921`](https://github.com/westondunn/nextup-get-hired/commit/0086921bf54a0c3539b53e431d48c7cb9286a39f)) the connection table, [#53](https://github.com/westondunn/nextup-get-hired/pull/53) ([`a53ab09`](https://github.com/westondunn/nextup-get-hired/commit/a53ab0962400eaf4b14e355545606e441775092a)) client saving, and [#54](https://github.com/westondunn/nextup-get-hired/pull/54) ([`44e8cd6`](https://github.com/westondunn/nextup-get-hired/commit/44e8cd6e3426dd75d23e4514d77d777b23d9167e)) the consent flow. [#55](https://github.com/westondunn/nextup-get-hired/pull/55) ([`328bdfc`](https://github.com/westondunn/nextup-get-hired/commit/328bdfcf9629c319efeceb8501f299844dc9aa97)) connected both sync workers to the saved grant. [#56](https://github.com/westondunn/nextup-get-hired/pull/56) ([`4589435`](https://github.com/westondunn/nextup-get-hired/commit/45894352e15d67453839377c913eaea4274b7e70)) delivered the Settings card.

| Criterion in #10 | Implementation and verification |
| --- | --- |
| Wrong or replayed state | The [consent routes](../../backend/app/google_consent.py) consume a short-lived, single-use flow. [Consent tests](../../backend/tests/test_google_consent.py) cover unknown, expired and replayed state. [OAuth tests](../../backend/tests/test_google_oauth.py) cover the S256 challenge, server-side verifier and matching redirect address. |
| Declined consent or no requested capability granted | A refusal stores no new grant. A first connection stays disconnected. A failed or declined reconnect preserves the earlier connection. Settings displays fixed outcomes and provides the connect control when available. With no requested capability granted, the callback attempts revocation only when neither a stored grant nor a complete configuration fallback exists. Otherwise it discards the returned token without revocation. Provider refusal or unavailability cannot establish successful revocation. [Callback decisions](../../backend/app/google_consent.py), [mocked refusal cases](../../backend/tests/test_google_consent.py), [database preservation tests](../../backend/tests/test_google_connection_integration.py), [Settings messages](../../frontend/src/hub/google-api.ts). |
| Partial consent | The callback stores the granted scopes. Each worker checks its own scope. Settings identifies the enabled capabilities absent from the stored grant. Its comparison uses installation settings, independently of the last form selection. [Stored grant tests](../../backend/tests/test_google_connection_integration.py), [credential selection](../../backend/app/google_credentials.py), [per-capability tests](../../backend/tests/test_google_credentials.py), [Settings card tests](../../frontend/src/hub/GoogleConnectionCard.test.tsx). |
| Callback binding and log redaction | Missing or mismatched browser binding is refused. The [callback tests](../../backend/tests/test_google_consent.py) exercise binding and Uvicorn access logging. The [Vite proxy test](../../frontend/src/vite-proxy-log.test.ts) checks proxy-error logs, and the [running-service check](../../backend/tests/test_integration.py) covers the fixture stack. |
| Tokens stay server-side and out of logs | The [token vault](../../backend/app/token_vault.py) seals the refresh token and client secret with a separate file-based key. The callback redirects with a fixed outcome. Tests cover [encryption and key mismatch](../../backend/tests/test_token_vault.py), [status responses](../../backend/tests/test_google_connection.py), [response and log redaction](../../backend/tests/test_google_consent.py), and [credential storage and sync](../../backend/tests/test_google_connection_integration.py). The [migration tests](../../backend/tests/test_migrations_integration.py) cover the `oss_0031` round trip and refusal to downgrade while a connection row exists. |
| Nothing configured | The sync flags remain off in every shipped configuration. Core use continues without a Google account. The card is inert while locked and explains unavailability when unlocked. [Configuration and sync tests](../../backend/tests/test_google_credentials.py), [card tests](../../frontend/src/hub/GoogleConnectionCard.test.tsx), [browser checks](../../frontend/tests/google.spec.ts). |

[Hosted CI at the last implementation merge](https://github.com/westondunn/nextup-get-hired/actions/runs/43777493105) and [hosted CI at the review commit](https://github.com/westondunn/nextup-get-hired/actions/runs/45308431555) passed. At the review commit the migration round trips, backend, frontend and browser checks passed. The [verification artifact](https://github.com/westondunn/nextup-get-hired/actions/runs/45308431555/artifacts/14882606822) records a complete disclosure audit with zero disclosures. Focused local tests at that commit passed 418 backend tests with 208 subtests and 41 frontend tests. The local review did not rerun the full disposable stack. Browser checks cover the locked card, return to Settings and session refusals. Google responses in the consent tests are simulated. Gmail (`Correspondence: read`) and Google Calendar (`Calendar: read`) are both **Implemented, disabled**, with support status **None**. Provider-side enforcement and clean-machine setup remain unvalidated. See the [integration matrix](../INTEGRATIONS.md) and [#14](https://github.com/westondunn/nextup-get-hired/issues/14).

On 2026-11-23 the maintainer approved reconciling #10 with the failure behavior recorded in [PR #54](https://github.com/westondunn/nextup-get-hired/pull/54). A failed first attempt leaves the installation disconnected. A failed or declined reconnect preserves the earlier connection and stores no new grant. A grant containing none of the requested capabilities follows the conditional, best-effort revocation rule above. [Issue #11](https://github.com/westondunn/nextup-get-hired/issues/11) covers lifecycle management.

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
