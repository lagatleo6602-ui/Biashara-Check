"""Encryption for contact details (proposal 3.12: encrypted storage).

The key comes from CONTACT_KEY in .env, or is created once in instance/contact.key.
BACK THIS KEY UP: without it, saved emails and phone numbers can't be read.
"""
import base64
import hashlib
import hmac
import os
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

KEY_FILE = Path(__file__).resolve().parents[1] / "instance" / "contact.key"


@lru_cache
def _key() -> bytes:
    env = os.getenv("CONTACT_KEY", "").strip()
    if env:
        return env.encode()
    if not KEY_FILE.exists():
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        KEY_FILE.write_bytes(Fernet.generate_key())
    return KEY_FILE.read_bytes().strip()


def _fernet() -> Fernet:
    return Fernet(_key())


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return "(can't be read: wrong encryption key)"


def blind_index(kind: str, value: str) -> str:
    """Keyed hash so an email/phone can be looked up without storing it in plain text."""
    secret = hashlib.sha256(b"blind-index:" + base64.urlsafe_b64decode(_key())).digest()
    return hmac.new(secret, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()
