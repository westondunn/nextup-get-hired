"""Google OAuth calls for the stored connection. Every provider call is mocked."""

import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.config import Settings
from app.sources import gmail, google_calendar, google_oauth
from app.sources.common import SourceError
from app.sources.google_oauth import Grant

CLIENT_ID = "123456789012-synthetic0client.apps.googleusercontent.com"
CLIENT_SECRET = "SYNTHETIC-client-secret-that-must-never-leak"
CODE = "4/synthetic-authorization-code"
VERIFIER = "synthetic-verifier-" + "v" * 40
REDIRECT = "http://127.0.0.1:15173/api/google/callback"
ACCESS = "synthetic-access-token"
REFRESH = "synthetic-refresh-token"
LIVE = Settings()
TOKEN_RESPONSE = {
    "access_token": ACCESS,
    "refresh_token": REFRESH,
    "expires_in": 3599,
    "scope": f"{gmail.SCOPE} {google_calendar.SCOPE}",
    "token_type": "Bearer",
}


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def exchange(client, settings=LIVE):
    return google_oauth.exchange_code(
        client,
        settings,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        code=CODE,
        verifier=VERIFIER,
        redirect_uri=REDIRECT,
    )


# ---------- the consent address ----------


def test_the_challenge_is_the_s256_form_of_the_verifier():
    # The example of RFC 7636, appendix B.
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert google_oauth.code_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    digest = hashlib.sha256(VERIFIER.encode()).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert google_oauth.code_challenge(VERIFIER) == expected


@pytest.mark.parametrize(
    "capabilities,scope",
    [
        (("gmail",), gmail.SCOPE),
        (("calendar",), google_calendar.SCOPE),
        (("gmail", "calendar"), f"{gmail.SCOPE} {google_calendar.SCOPE}"),
    ],
)
def test_the_consent_address_asks_only_for_the_selected_capabilities(capabilities, scope):
    address = google_oauth.authorization_url(
        client_id=CLIENT_ID,
        redirect_uri=REDIRECT,
        capabilities=capabilities,
        state="synthetic-state",
        verifier=VERIFIER,
    )
    parts = urlsplit(address)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == google_oauth.AUTHORIZATION_URL
    assert parse_qs(parts.query, strict_parsing=True) == {
        "client_id": [CLIENT_ID],
        "redirect_uri": [REDIRECT],
        "response_type": ["code"],
        "scope": [scope],
        "access_type": ["offline"],
        "prompt": ["consent"],
        "include_granted_scopes": ["true"],
        "state": ["synthetic-state"],
        "code_challenge": [google_oauth.code_challenge(VERIFIER)],
        "code_challenge_method": ["S256"],
    }
    # The verifier and the client secret stay on the server.
    assert VERIFIER not in address and CLIENT_SECRET not in address


def test_only_the_two_read_only_scopes_are_known():
    assert google_oauth.CAPABILITY_SCOPES == {
        "gmail": "https://www.googleapis.com/auth/gmail.readonly",
        "calendar": "https://www.googleapis.com/auth/calendar.readonly",
    }


# ---------- the code exchange ----------


def test_the_exchange_sends_the_code_the_verifier_and_the_same_redirect_address():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=TOKEN_RESPONSE)

    with client_for(handler) as client:
        grant = exchange(client)
    (request,) = seen
    assert (request.method, str(request.url)) == ("POST", google_oauth.TOKEN_URL)
    assert parse_qs(request.content.decode(), strict_parsing=True) == {
        "code": [CODE],
        "client_id": [CLIENT_ID],
        "client_secret": [CLIENT_SECRET],
        "redirect_uri": [REDIRECT],
        "grant_type": ["authorization_code"],
        "code_verifier": [VERIFIER],
    }
    assert (grant.access_token, grant.refresh_token) == (ACCESS, REFRESH)
    assert grant.scopes == {gmail.SCOPE, google_calendar.SCOPE}
    assert grant.capabilities() == ("gmail", "calendar")


def test_a_grant_cannot_be_printed():
    grant = Grant(access_token=ACCESS, refresh_token=REFRESH, scopes=frozenset({gmail.SCOPE}))
    assert ACCESS not in repr(grant) and REFRESH not in repr(grant)
    assert ACCESS not in str(grant) and REFRESH not in str(grant)


@pytest.mark.parametrize(
    "scope,capabilities",
    [
        (gmail.SCOPE, ("gmail",)),
        (google_calendar.SCOPE, ("calendar",)),
        ("https://www.googleapis.com/auth/gmail.modify openid", ()),
        ("", ()),
        (f"openid {google_calendar.SCOPE}", ("calendar",)),
    ],
)
def test_capabilities_come_from_the_scopes_google_returned(scope, capabilities):
    with client_for(lambda r: httpx.Response(200, json={**TOKEN_RESPONSE, "scope": scope})) as c:
        assert exchange(c).capabilities() == capabilities


def test_a_missing_refresh_token_is_reported_as_empty():
    payload = {k: v for k, v in TOKEN_RESPONSE.items() if k != "refresh_token"}
    with client_for(lambda r: httpx.Response(200, json=payload)) as client:
        assert exchange(client).refresh_token == ""


REFUSAL = {"error": "invalid_grant", "error_description": "GOOGLE-TEXT-THAT-MUST-NOT-BE-REPEATED"}


@pytest.mark.parametrize(
    "response,code",
    [
        (httpx.Response(400, json=REFUSAL), "exchange_refused"),
        (httpx.Response(401, json=REFUSAL), "exchange_refused"),
        (httpx.Response(302, headers={"location": "https://example.invalid/"}), "exchange_refused"),
        (httpx.Response(429, json=REFUSAL), "provider_unavailable"),
        (httpx.Response(503, text="GOOGLE-TEXT-THAT-MUST-NOT-BE-REPEATED"), "provider_unavailable"),
        (httpx.Response(200, text="GOOGLE-TEXT-THAT-MUST-NOT-BE-REPEATED"), "invalid_response"),
        (httpx.Response(200, json=[TOKEN_RESPONSE]), "invalid_response"),
        (httpx.Response(200, json={**TOKEN_RESPONSE, "access_token": ""}), "invalid_response"),
        (httpx.Response(200, json={**TOKEN_RESPONSE, "access_token": 7}), "invalid_response"),
        (httpx.Response(200, json={**TOKEN_RESPONSE, "refresh_token": 7}), "invalid_response"),
        (httpx.Response(200, json={**TOKEN_RESPONSE, "refresh_token": "a b"}), "invalid_response"),
        (httpx.Response(200, json={**TOKEN_RESPONSE, "scope": None}), "invalid_response"),
        (httpx.Response(200, json={**TOKEN_RESPONSE, "scope": "x" * 201}), "invalid_response"),
        (
            httpx.Response(200, json={**TOKEN_RESPONSE, "scope": " ".join(["s"] * 51)}),
            "invalid_response",
        ),
        (
            httpx.Response(200, json={**TOKEN_RESPONSE, "padding": "x" * 70_000}),
            "invalid_response",
        ),
    ],
)
def test_a_failed_exchange_has_a_fixed_code_and_repeats_nothing(response, code):
    with client_for(lambda request: response) as client:
        with pytest.raises(SourceError) as caught:
            exchange(client)
    assert caught.value.code == code
    text = f"{caught.value.message} {caught.value!r} {caught.value.args}"
    for value in ("GOOGLE-TEXT", "invalid_grant", CODE, CLIENT_SECRET, VERIFIER, ACCESS, REFRESH):
        assert value not in text


def test_an_unreachable_token_endpoint_is_a_network_error():
    def handler(request):
        raise httpx.ConnectError("synthetic outage naming " + CLIENT_SECRET)

    with client_for(handler) as client:
        with pytest.raises(SourceError) as caught:
            exchange(client)
    assert caught.value.code == "network_error"
    assert CLIENT_SECRET not in caught.value.message
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


# ---------- which account consented ----------


def grant_of(*scopes):
    return Grant(access_token=ACCESS, refresh_token=REFRESH, scopes=frozenset(scopes))


def lookups(profile, calendar, seen):
    def handler(request):
        seen.append(request)
        assert request.method == "GET"
        assert request.headers["authorization"] == f"Bearer {ACCESS}"
        if str(request.url) == f"{gmail.API_BASE}/profile":
            return profile
        if str(request.url) == google_oauth.PRIMARY_CALENDAR_URL:
            return calendar
        raise AssertionError("request to an unexpected address")

    return handler


def addresses(grant, profile=None, calendar=None, seen=None):
    profile = profile or httpx.Response(200, json={"emailAddress": "Person@Example.Test"})
    calendar = calendar or httpx.Response(200, json={"id": "Person@Example.Test", "summary": "x"})
    with client_for(lookups(profile, calendar, [] if seen is None else seen)) as client:
        return google_oauth.account_addresses(client, LIVE, grant)


def test_the_account_is_read_from_gmail_when_only_mail_was_granted():
    seen = []
    assert addresses(grant_of(gmail.SCOPE), seen=seen) == ("person@example.test",)
    assert [str(r.url) for r in seen] == [f"{gmail.API_BASE}/profile"]


def test_the_account_is_read_from_the_primary_calendar_when_only_calendar_was_granted():
    seen = []
    assert addresses(grant_of(google_calendar.SCOPE), seen=seen) == ("person@example.test",)
    assert [str(r.url) for r in seen] == [google_oauth.PRIMARY_CALENDAR_URL]


def test_both_addresses_are_read_when_both_were_granted_and_the_mailbox_comes_first():
    seen = []
    both = grant_of(gmail.SCOPE, google_calendar.SCOPE, "openid")
    assert addresses(both, seen=seen) == ("person@example.test",)  # the same address once
    assert len(seen) == 2
    calendar = httpx.Response(200, json={"id": "other.name@example.test"})
    assert addresses(both, calendar=calendar) == ("person@example.test", "other.name@example.test")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"emailAddress": ""},
        {"emailAddress": "not-an-address"},
        {"emailAddress": "two@signs@example.test"},
        {"emailAddress": "spa ce@example.test"},
        {"emailAddress": "a" * 65 + "@example.test"},
        {"emailAddress": ["person@example.test"]},
    ],
)
def test_an_answer_without_a_usable_address_is_refused(payload):
    with pytest.raises(SourceError) as caught:
        addresses(grant_of(gmail.SCOPE), profile=httpx.Response(200, json=payload))
    assert caught.value.code == "no_account"


def test_no_request_is_made_for_a_grant_with_neither_capability():
    seen = []
    with pytest.raises(SourceError) as caught:
        addresses(grant_of("openid"), seen=seen)
    assert caught.value.code == "no_account" and seen == []


@pytest.mark.parametrize("failing", ["profile", "calendar"])
def test_a_failed_account_lookup_keeps_its_provider_code(failing):
    with pytest.raises(SourceError) as caught:
        addresses(grant_of(gmail.SCOPE, google_calendar.SCOPE), **{failing: httpx.Response(503)})
    assert caught.value.code == "provider_unavailable"


# ---------- revocation ----------


def test_revocation_sends_the_token_in_the_body_only():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={})

    with client_for(handler) as client:
        assert google_oauth.revoke(client, LIVE, REFRESH) is True
    (request,) = seen
    assert (request.method, str(request.url)) == ("POST", google_oauth.REVOCATION_URL)
    assert parse_qs(request.content.decode(), strict_parsing=True) == {"token": [REFRESH]}
    assert REFRESH not in str(request.url)


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 503])
def test_a_refused_revocation_is_reported_not_raised(status):
    with client_for(lambda request: httpx.Response(status, json=REFUSAL)) as client:
        assert google_oauth.revoke(client, LIVE, REFRESH) is False


def test_an_unreachable_revocation_endpoint_is_reported_not_raised():
    def handler(request):
        raise httpx.ConnectTimeout("synthetic outage")

    with client_for(handler) as client:
        assert google_oauth.revoke(client, LIVE, REFRESH) is False
