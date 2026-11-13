# Security

NextUp is pre-release software and is not ready for production use.

## Known limits

- The API has no authentication. The shipped configurations publish ports on the loopback interface only. Do not expose NextUp to a network.
- The API accepts only requests addressed to `localhost` or `127.0.0.1`, and refuses state-changing requests that a browser reports as coming from another site. This limits what a web page open in your browser can do to a local instance. It is not authentication: any program running on the same machine can still call the API.
- The database safeguards (separate roles, the migration guard) are still being validated and should not be relied on yet.
- Only the newest state of the main branch is maintained. There are no security updates for older versions.

## Reporting a vulnerability

Please do not describe a vulnerability in a public issue.

Use GitHub's private vulnerability reporting for this repository ("Report a vulnerability" under the Security tab). If that option is not available, open an issue that asks for a private contact and contains no details.

Include what you observed, how to reproduce it and which commit you used. Never include real credentials or personal data in a report.

There is no bounty programme and no guaranteed response time.
