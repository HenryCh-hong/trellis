"""At-rest encryption helpers.

Scope note: this product never stores a third-party password (see
``docs/privacy.md``).  The only secrets we hold are things like an optional
Apple Shortcuts webhook token, so a single locally-generated Fernet key is
proportionate.  Key material lives in a 0600 file outside the repo tree in
production deployments.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


def _load_or_create_key(path: Path) -> bytes:
    if path.exists():
        return path.read_bytes().strip()
    key = Fernet.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key)
    os.chmod(path, 0o600)
    return key


def _fernet() -> Fernet:
    return Fernet(_load_or_create_key(get_settings().secret_key_file))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str | None:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def sha256_b64(data: bytes) -> str:
    import hashlib

    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
