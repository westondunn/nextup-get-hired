"""Encryption for the credentials of a stored connection.

See docs/decisions/0003-google-connection.md, section 6. The key is a secret file that only
the api and worker services receive. It protects a copy of the database taken without the
key; it does not protect against a process running as the same operating-system user.

A sealed value is text: a format version, then the nonce and ciphertext. The purpose given
when sealing is authenticated with it, so a value sealed for one field cannot be opened as
another. Nothing here logs, and no error carries a value.
"""

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import Settings, get_settings

FORMAT = "v1"
MIN_KEY_LENGTH = 32
NONCE_BYTES = 12
TAG_BYTES = 16
_DERIVATION = b"nextup stored connection credentials v1"

NO_KEY = "No encryption key is configured."
UNREADABLE = "The stored value could not be decrypted."


class VaultError(Exception):
    """Sealing or opening failed. ``code`` is ``no_key`` or ``unreadable``."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(NO_KEY if code == "no_key" else UNREADABLE)


def _cipher(settings: Settings | None) -> AESGCM:
    secret = (settings or get_settings()).token_key.get_secret_value()
    if len(secret) < MIN_KEY_LENGTH:
        raise VaultError("no_key")
    derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_DERIVATION)
    return AESGCM(derived.derive(secret.encode()))


def available(settings: Settings | None = None) -> bool:
    """Whether a usable key is configured. Never raises."""
    try:
        _cipher(settings)
    except VaultError:
        return False
    return True


def seal(plaintext: str, *, purpose: str, settings: Settings | None = None) -> str:
    """Encrypt ``plaintext`` for the field named by ``purpose``."""
    cipher = _cipher(settings)
    nonce = os.urandom(NONCE_BYTES)
    sealed = cipher.encrypt(nonce, plaintext.encode(), purpose.encode())
    return f"{FORMAT}.{base64.urlsafe_b64encode(nonce + sealed).decode()}"


def open_sealed(sealed: str, *, purpose: str, settings: Settings | None = None) -> str:
    """Decrypt a value sealed for ``purpose``. Anything else raises ``unreadable``."""
    cipher = _cipher(settings)
    if not isinstance(sealed, str):
        raise VaultError("unreadable")
    version, _, encoded = sealed.partition(".")
    if version != FORMAT:
        raise VaultError("unreadable")
    try:
        raw = base64.b64decode(encoded, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError):
        raise VaultError("unreadable") from None
    if len(raw) < NONCE_BYTES + TAG_BYTES:
        raise VaultError("unreadable")
    try:
        return cipher.decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], purpose.encode()).decode()
    except (InvalidTag, UnicodeDecodeError):
        raise VaultError("unreadable") from None
