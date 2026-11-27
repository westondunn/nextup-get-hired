# 0004 — Authenticated private ingress for staging

**Proposed for maintainer review.**

Written November 27, 2026 against `1b369c6`.

## Context

A single-user staging operator wants to open the workspace from a second device on a private network. Today the frontend forwards the browser's Host to the API, which accepts loopback names in staging. Most workspace reads require no session. The setup-code session protects selected integration and credential operations. These constraints are documented in [decision 0001](0001-local-session-boundary.md) and [the security policy](../../SECURITY.md).

## Proposed decision

Keep loopback as the default. Introduce a separate, explicitly enabled staging deployment mode after its authentication, packaging and tests have been reviewed. Enabling it requires one exact external HTTPS origin and one authorized operator identity. Missing or invalid configuration prevents startup in this mode. Multi-user data separation is outside this proposal.

1. **Authenticate the entire workspace.** An identity-aware gateway authenticates the operator and authorizes their identity before serving the UI, static assets, downloads or any API route, including reads and detailed health. Browser sign-in and its callback belong to the gateway. API clients receive 401 when unauthenticated and 403 when signed in as the wrong operator. Upstream outages and unverifiable identities fail closed.
2. **Enforce the boundary at the upstream.** Serve the built frontend through the authenticated path. Give the gateway a dedicated upstream connection to that frontend. Keep the API and data services off the ingress network. In this mode, remove direct host publications for the frontend and API. Require verifiable evidence of authorized access at the API, such as a short-lived signed assertion with a pinned issuer, audience and operator subject. Discard incoming client identity headers at the gateway. An ordinary header, a source address or a private network alone cannot establish identity.
3. **Validate the browser's origin.** Preserve the browser's Host through the proxy. Validate exactly one authority against the configured HTTPS origin, including its effective port. Cookie-authenticated state changes require a matching HTTPS Origin and retain the existing Fetch Metadata checks. Require host-only Secure and HttpOnly session cookies with an explicit SameSite policy. Verify any backend trust material through configuration independent of request headers.
4. **Preserve sensitive-operation controls.** The gateway identity and the local setup-code session serve different purposes. Continue to require the latter on existing protected routes and preserve staging's disabled integrations. [Decision 0003](0003-google-connection.md) documents the Google callback's separate flow checks. Keep it unavailable externally in this staging mode. Give container liveness checks a dedicated private probe with no workspace or diagnostic data.

## Backend verification available for review

The alternate ASGI factory `app.gateway:create_app` wraps the staging runtime API. Its startup guard, loopback Host rules, Origin checks and setup-code sessions still apply. The shipped Compose files use the original entrypoint.

The factory reads its policy at startup from `/run/secrets/nextup_gateway_policy`. Supply one UTF-8 JSON line, at most 4,096 bytes, with exactly four string fields. The file must be owned by UID 0 and readable by the runtime. Use mode `0440` with the runtime's group and a regular file at the fixed path. Encode PEM line breaks as JSON escapes.

| Policy field | Value |
| --- | --- |
| `issuer` | Exact expected `iss` value from the assertion signer |
| `audience` | Exact expected `aud` string for this API |
| `subject` | Exact `sub` identifying the single authorized operator |
| `public_key` | PEM-encoded RSA public verification key of at least 2,048 bits |

Each HTTP request requires one `X-NextUp-Gateway-Assertion` header containing a compact RS256 JWT of at most 8,192 bytes, with type `nextup-gateway+jwt`. The issuer must supply integer `iat` and `exp` claims with a positive lifetime of at most 120 seconds. The verifier checks expiry and any `nbf` against its clock with zero leeway. It rejects an invalid assertion with 401 and a verified assertion for another operator with 403. It removes the assertion header before forwarding an authorized request.

The wrapper also protects `/api/live`. The current Compose liveness probe sends an unsigned request and would receive 401 from this factory. A private probe, gateway sign-in and assertion issuance, frontend protection, exact external-origin handling and end-to-end tests are prerequisites for deployment.

## Acceptance evidence required before enabling

| Test | Expected result |
| --- | --- |
| Default deployment | Existing loopback browser and API checks pass. A named network host is refused. |
| Anonymous or unauthorized client | The UI requires sign-in. API reads, writes, detailed health and downloads return 401 without an identity and 403 for a different signed-in operator. |
| Authorized synthetic operator | The browser opens Today and can read and write a synthetic test record. A protected integration operation still requires its local session. |
| Wrong origin or authority | Unknown or ambiguous Host is refused. Authenticated writes from the wrong scheme, host or port, or with a missing Origin or disallowed Fetch Metadata, return 403. No record changes. |
| Direct access and failed identity checks | Direct network access cannot serve the application anonymously. An absent, expired or invalid assertion is rejected. An authorization service outage returns no workspace content. |
| Operations | The private probe supports container health. Access logs omit credentials, cookie values, assertions, OAuth query strings and record content. |

Run the tests with a disposable identity fixture and synthetic records. Provider credentials, live OAuth grants and production data are unnecessary. Review the assertion issuer and verifier, operator revocation, session expiry and the trusted certificate workflow before claiming network access is supported.

## Rollback

Withdraw the gateway route first and revoke the private-access sessions. Restore the reviewed loopback deployment against its existing volumes and verify local health plus rejection of the network hostname. This mode requires no schema or data migration.
