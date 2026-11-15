# Security

NextUp is pre-release software and is not ready for production use.

## Known limits

- The API has no authentication. The shipped configurations publish ports on the loopback interface only. Do not expose NextUp to a network.
- The API accepts only requests addressed to `localhost` or `127.0.0.1`, and refuses state-changing requests that a browser reports as coming from another site. This limits what a web page open in your browser can do to a local instance. It is not authentication: any program running on the same machine can still call the API.
- Changing or running mail and calendar sync, saving or reading a Google client, and starting a Google connection require a local session, started by entering the installation's setup code in Settings. The address Google sends the browser back to cannot require the session, because the browser does not send the session cookie on a navigation from another site. It completes only a connection that a session started, in the same browser, within ten minutes, once. Every other route, including every route that reads your data, needs no session. A program running as your own operating-system user can read the setup code file, so the session guards against other local accounts and accidental use, not against your own account being compromised.
- Connecting a Google account authorizes NextUp to read from Google. The routes for it exist, but refuse in every shipped configuration, and have been tested with simulated Google responses only. It is not a login to NextUp and does not protect the API.
- The database safeguards (separate roles, the migration guard) are still being validated and should not be relied on yet.
- Only the newest state of the main branch is maintained. There are no security updates for older versions.

## Reporting a vulnerability

Please do not describe a vulnerability in a public issue.

Use GitHub's private vulnerability reporting for this repository ("Report a vulnerability" under the Security tab). If that option is not available, open an issue that asks for a private contact and contains no details.

Include what you observed, how to reproduce it and which commit you used. Never include real credentials or personal data in a report.

There is no bounty programme and no guaranteed response time.
