# 0001 — Local request boundary for the API

- **Status:** Accepted by the maintainer on 2026-11-13. Nothing described here is implemented yet.
- **Date:** 2026-11-13, written against commit `3d02615`.
- **Tracking:** decision [#7](https://github.com/westondunn/nextup-get-hired/issues/7); implementation [#8](https://github.com/westondunn/nextup-get-hired/issues/8) (layers 1 and 2) and [#18](https://github.com/westondunn/nextup-get-hired/issues/18) (layer 3); part of [#3](https://github.com/westondunn/nextup-get-hired/issues/3).

## Context

NextUp is a single-user application whose API has no authentication. The shipped configurations publish the API and the web interface on the loopback interface only, and [SECURITY.md](../../SECURITY.md) tells users not to expose them to a network.

The planned Google connection ([#9](https://github.com/westondunn/nextup-get-hired/issues/9), [#10](https://github.com/westondunn/nextup-get-hired/issues/10)) adds routes that start an authorization flow, store a token and remove it. Before those routes exist, the API needs a boundary that does not depend on loopback binding alone, because binding to loopback leaves three kinds of caller able to reach it:

1. **A web page in the user's browser.** A page from any site can send requests to a loopback port. The browser stops that page from reading the response, but the request is still delivered.
2. **A page using DNS rebinding.** A site can point its own name at `127.0.0.1`. The browser then treats the local API as that site's own origin, so the page can read responses as well.
3. **Another process or user on the same machine.** Loopback ports are reachable by every local account.

Google account authorization does not help with any of these. It proves to Google who the user is; it does not identify the person using NextUp.

### How requests reach the API today

| Path | `Host` header the API sees | Evidence |
| --- | --- | --- |
| Browser to the web interface, which proxies `/api` | The browser's host, for example `127.0.0.1:15173`, once the proxy sets `changeOrigin: false` (see the correction below) | `frontend/vite.config.ts`, `compose.dev.yaml` |
| Browser or tool directly to the published API port | `127.0.0.1:18000` or `localhost:18000` | `compose.dev.yaml`, `compose.staging.yaml` |
| Container health check | `127.0.0.1:8000` | `compose.base.yaml` |
| CI browser tests | `frontend:5173` | `compose.ci.yaml` |
| CI API tests inside the stack | `api:8000` | `backend/tests/test_integration.py` |
| Unit tests | `testserver` | `backend/tests/test_api.py` |

Other facts that shape the decision:

- `backend/app/main.py` installs no middleware. There is no CORS configuration, which is correct and should stay that way.
- The API has 39 `GET` routes and 57 routes using `POST`, `PUT` or `DELETE`.
- The frontend calls the API with relative `/api/...` URLs from four modules (`jobs-api.ts`, `profile-api.ts`, `retention-api.ts`, `api.ts`), not all through the shared `request` helper.
- The Vite development server already restricts its own `Host` header (`allowedHosts`), but the API port is published separately and bypasses it.

## Decision

Add three layers. The first two apply to every route and need nothing from the user. The third applies only to routes that manage integrations and credentials.

### Layer 1 — Host allowlist, all requests

The API refuses any request whose `Host` name is not on a fixed list:

- `localhost` and `127.0.0.1` in every environment, with any port;
- `api` and `frontend` only when `NEXTUP_ENV` is `ci` or `test`;
- `testserver` only in unit tests, supplied by the test fixture.

The list is a constant in the code, not a setting. This defeats DNS rebinding, because a rebinding request carries the attacker's host name.

### Layer 2 — Cross-origin refusal, state-changing requests

For `POST`, `PUT`, `PATCH` and `DELETE`, the API refuses a request when either of these is true:

- the `Sec-Fetch-Site` header is present and is neither `same-origin` nor `none`;
- the `Origin` header is present and its host and port differ from the request's `Host` header.

A request with neither header is treated as coming from a non-browser client and passes this layer. This is the Fetch Metadata approach described in the [OWASP CSRF prevention cheat sheet][owasp-csrf] and uses the [`Sec-Fetch-Site`][mdn-sfs] header that current browsers send on every request. It needs no token, so nothing is stored in the browser and the four frontend API modules do not change.

It depends on the Vite proxy passing the browser's `Host` header through unchanged. The implementation must include a test that fails if that changes.

**Correction, 2026-11-13.** This record first said that passing `Host` through was the proxy's default. That was wrong for the configuration in use: when a proxy target is written as a plain string, Vite sets `changeOrigin: true` and sends the target's host name (`api:8000`) instead. It was found by running the implementation against the development stack, where every proxied request was refused by layer 1. The proxy is therefore configured as an object with `changeOrigin: false`, and a frontend test guards that setting. The decision itself is unchanged.

The implementation must also confirm that no `GET` route changes state. Any that does becomes a `POST` first.

### Layer 3 — Local session, integration and credential routes

Layers 1 and 2 stop browser-based attacks but not another local process. Routes that manage integrations and credentials therefore also require a session:

- The launcher generates a setup code as a file under `.secrets/<env>/`, in the same way it generates database passwords. It never prints the code.
- The user reads the file and enters the code once in Settings. The API compares it in constant time and issues a session.
- The session is a random identifier in a cookie marked `HttpOnly`, `SameSite=Strict` and `Path=/api`. Only a hash of the identifier is stored, in the Redis instance the stack already runs.
- A session ends after 12 hours of inactivity and after 7 days at most. The user can end one from Settings.

Routes in scope when layer 3 first ships:

- `PUT /api/correspondence` and `POST /api/correspondence/sync`, which switch sync on and trigger it;
- every route added for the Google connection ([#10](https://github.com/westondunn/nextup-get-hired/issues/10), [#11](https://github.com/westondunn/nextup-get-hired/issues/11)).

The rest of the application stays usable without a session, so the default installation needs no extra step.

### Refusal behaviour

| Condition | Response |
| --- | --- |
| Host not on the list | `400` with a fixed message |
| Cross-origin state-changing request | `403` with a fixed message |
| Protected route without a valid session | `401` with a fixed message |
| Wrong setup code | `401` with the same fixed message, after a short fixed delay |

Messages and log lines are value-free: they never include a header value, the setup code or a session identifier.

## Alternatives considered

| Alternative | Why not |
| --- | --- |
| Rely on loopback binding only | Leaves all three callers in the context section unaddressed |
| Stop publishing the API port and serve only through the web interface | Removes the direct path but not the proxied one; also breaks the documented host-side development setup. Could be revisited separately |
| Per-request CSRF token in a header | Works, but needs a token in page state and a change to every API module, for no gain over layer 2 in current browsers |
| A full login for every route | Adds a first-run step to an application that otherwise needs none, and implies account features NextUp does not have |
| Layers 1 and 2 only, no session | Leaves credential routes open to any local process. Acceptable for today's routes; not for token storage |
| A configurable host list | A setting that can be widened invites exposing the API to a network, which the project does not support |

## What this does not change

- The API is still not safe to expose to a network. Ports stay on loopback and `SECURITY.md` keeps saying so.
- A process running as the same operating-system user can read `.secrets/` and is not stopped by layer 3. The session protects against other local accounts and against accidental use, not against the user's own account being compromised.
- Cookies are shared across ports on the same host name, so another local web service on `localhost` receives the session cookie. The identifier is opaque and useless without the API, but this is a reason to keep sessions short-lived.
- Routes outside layer 3 remain callable by local non-browser clients without a session.

## Implementation slices

This is larger than one reviewable change, so it is tracked as two issues:

1. **Layers 1 and 2** on all routes ([#8](https://github.com/westondunn/nextup-get-hired/issues/8)). No user-visible change, no migration. Tests for each refusal, for every access path in the table above, and for the proxy assumption.
2. **Layer 3** ([#18](https://github.com/westondunn/nextup-get-hired/issues/18)): setup code in the launcher, session routes, the Settings prompt with accessibility coverage, and protection of the two correspondence routes. No migration.

The Google connection work depends on both.

## Decisions on the questions raised in review

The maintainer accepted the proposed answers on 2026-11-13.

| Question | Decision |
| --- | --- |
| Session storage | Redis, under a key derived from a hash of the session identifier, with key expiry enforcing the idle limit. Sessions survive a restart because the stack runs Redis with persistence. See the amendment below |
| Session lifetime | 12 hours of inactivity, 7 days at most |
| Scope of layer 3 | The two correspondence routes and the Google connection routes only. Export, seed import and retention routes are not included in the first slice |
| Staging | Same rules as development, with no additional host names |

### Amendment, 2026-11-13: session storage

The first accepted answer was a database table. That was changed to Redis before any code was written, with the maintainer's agreement, for these reasons:

- A table would have been the first migration added after the 29 pinned revisions. That path through the migration guard has never been used for a real revision, and it deserves its own focused change, not a place inside a session feature.
- The stack already runs Redis with persistence, and the API already connects to it for its health probe.
- Redis key expiry enforces the idle limit directly, and ending a session is deleting one key.

The cost is that sessions are lost if the Redis volume is lost, and the user then enters the setup code again. The first new migration is expected to arrive with the Google token store ([#10](https://github.com/westondunn/nextup-get-hired/issues/10)), where a table is unavoidable.

## References

- [OWASP Cross-Site Request Forgery Prevention Cheat Sheet][owasp-csrf] — Fetch Metadata headers as a CSRF defence.
- [MDN: `Sec-Fetch-Site`][mdn-sfs] — header values and browser support.
- [MDN: `Set-Cookie`][mdn-cookie] — `HttpOnly`, `SameSite` and `Path` attributes.

[owasp-csrf]: https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html
[mdn-sfs]: https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Sec-Fetch-Site
[mdn-cookie]: https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie
