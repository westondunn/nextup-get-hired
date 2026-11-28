"""Container-local liveness check for the gateway-authenticated staging API."""

import json
from contextlib import closing
from http.client import HTTPConnection, HTTPException

MAX_BODY_BYTES = 256


def main() -> int:
    """Succeed only when the local API returns the expected anonymous refusal."""
    try:
        with closing(HTTPConnection("127.0.0.1", 8000, timeout=3)) as connection:
            connection.request("GET", "/api/live")
            with connection.getresponse() as response:
                if response.status != 401 or response.getheader("Cache-Control") != "no-store":
                    return 1
                body = response.read(MAX_BODY_BYTES + 1)
                if len(body) > MAX_BODY_BYTES or response.length not in (None, 0):
                    return 1
                return 0 if json.loads(body) == {"detail": "Authentication required."} else 1
    except (OSError, HTTPException, ValueError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
