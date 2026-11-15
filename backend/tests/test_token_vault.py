"""The key that encrypts stored connection credentials, and the encryption itself."""

import base64
import os

import pytest
from pydantic import SecretStr

from app import token_vault as vault
from app.config import ConfigError, Settings, load_settings

KEY = "unit-test-only-token-key-0123456789abcdefghij"
OTHER_KEY = "unit-test-only-other-key-0123456789abcdefghi"
SECRET = "synthetic-refresh-token-value-that-must-never-leak"
WITH_KEY = Settings(token_key=SecretStr(KEY))


def environment(**extra):
    return {
        "NEXTUP_ENV": "dev",
        "NEXTUP_DB_HOST": "postgres",
        "NEXTUP_DB_NAME": "nextup_dev",
        "NEXTUP_DB_USER": "nextup_dev_app",
        "NEXTUP_DB_PASSWORD": "unit_test_only_not_a_real_password",
        **extra,
    }


# ---------- configuration ----------


def test_the_key_is_read_from_a_file_only(tmp_path):
    assert load_settings(environment()).token_key.get_secret_value() == ""
    path = tmp_path / "token_key"
    path.write_text(KEY + "\n")
    os.chmod(path, 0o600)
    loaded = load_settings(
        environment(NEXTUP_TOKEN_KEY_FILE=str(path), NEXTUP_SECRETS_DIR=str(tmp_path))
    )
    assert loaded.token_key.get_secret_value() == KEY
    with pytest.raises(ConfigError) as refused:
        load_settings(environment(NEXTUP_TOKEN_KEY=KEY))
    assert refused.value.code == "NXG-C16" and KEY not in str(refused.value)


def test_the_key_never_appears_in_settings_repr():
    assert KEY not in repr(WITH_KEY) and KEY not in str(WITH_KEY)


# ---------- sealing and opening ----------


def test_a_sealed_value_opens_again_and_hides_its_content():
    sealed = vault.seal(SECRET, purpose="google.refresh_token", settings=WITH_KEY)
    assert sealed.startswith("v1.") and SECRET not in sealed
    assert SECRET.encode() not in base64.urlsafe_b64decode(sealed[3:])
    assert vault.open_sealed(sealed, purpose="google.refresh_token", settings=WITH_KEY) == SECRET


def test_sealing_the_same_value_twice_gives_different_text():
    first = vault.seal(SECRET, purpose="p", settings=WITH_KEY)
    second = vault.seal(SECRET, purpose="p", settings=WITH_KEY)
    assert first != second
    assert vault.open_sealed(first, purpose="p", settings=WITH_KEY) == SECRET
    assert vault.open_sealed(second, purpose="p", settings=WITH_KEY) == SECRET


@pytest.mark.parametrize("value", ["", "a", "\u00e9\u4e2d\U0001f511", "x" * 10_000])
def test_any_text_survives_a_round_trip(value):
    sealed = vault.seal(value, purpose="p", settings=WITH_KEY)
    assert vault.open_sealed(sealed, purpose="p", settings=WITH_KEY) == value


def unreadable(sealed, *, purpose="p", settings=WITH_KEY):
    with pytest.raises(vault.VaultError) as caught:
        vault.open_sealed(sealed, purpose=purpose, settings=settings)
    assert caught.value.code == "unreadable"
    assert str(caught.value) == vault.UNREADABLE
    # No lower-level error, which could describe the value, is attached.
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None or caught.value.__suppress_context__
    return caught.value


def test_a_value_sealed_for_one_field_does_not_open_as_another():
    sealed = vault.seal(SECRET, purpose="google.refresh_token", settings=WITH_KEY)
    unreadable(sealed, purpose="google.client_secret")


def test_a_different_key_cannot_open_the_value():
    sealed = vault.seal(SECRET, purpose="p", settings=WITH_KEY)
    unreadable(sealed, settings=Settings(token_key=SecretStr(OTHER_KEY)))


def test_a_changed_value_is_refused():
    sealed = vault.seal(SECRET, purpose="p", settings=WITH_KEY)
    raw = bytearray(base64.urlsafe_b64decode(sealed[3:]))
    for position in (0, vault.NONCE_BYTES, len(raw) - 1):
        changed = bytearray(raw)
        changed[position] ^= 1
        unreadable("v1." + base64.urlsafe_b64encode(bytes(changed)).decode())
    unreadable("v1." + base64.urlsafe_b64encode(bytes(raw[:-1])).decode())


@pytest.mark.parametrize(
    "sealed",
    [
        "",
        "v1",
        "v1.",
        "v2." + "A" * 60,
        "v1.not base64!",
        "v1." + base64.urlsafe_b64encode(b"short").decode(),
        "v1." + base64.urlsafe_b64encode(b"\x00" * 28).decode(),
        SECRET,
        None,
        5,
        b"v1.AAAA",
    ],
    ids=lambda value: repr(value)[:20],
)
def test_anything_that_is_not_a_sealed_value_is_refused_without_detail(sealed):
    error = unreadable(sealed)
    assert SECRET not in str(error) and SECRET not in repr(error)


@pytest.mark.parametrize("key", ["", "short", "x" * (vault.MIN_KEY_LENGTH - 1)])
def test_nothing_is_sealed_or_opened_without_a_usable_key(key):
    settings = Settings(token_key=SecretStr(key))
    assert vault.available(settings) is False
    for attempt in (
        lambda: vault.seal(SECRET, purpose="p", settings=settings),
        lambda: vault.open_sealed("v1.AAAA", purpose="p", settings=settings),
    ):
        with pytest.raises(vault.VaultError) as caught:
            attempt()
        assert caught.value.code == "no_key" and str(caught.value) == vault.NO_KEY


def test_a_key_of_the_minimum_length_is_usable():
    settings = Settings(token_key=SecretStr("k" * vault.MIN_KEY_LENGTH))
    assert vault.available(settings) and vault.available(WITH_KEY)
    sealed = vault.seal(SECRET, purpose="p", settings=settings)
    assert vault.open_sealed(sealed, purpose="p", settings=settings) == SECRET


def test_the_key_comes_from_the_loaded_settings_when_none_are_passed(monkeypatch):
    monkeypatch.setattr(vault, "get_settings", lambda: WITH_KEY)
    sealed = vault.seal(SECRET, purpose="p")
    assert vault.open_sealed(sealed, purpose="p") == SECRET and vault.available()
    monkeypatch.setattr(vault, "get_settings", lambda: Settings())
    assert vault.available() is False
