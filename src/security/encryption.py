from __future__ import annotations

import base64
import hashlib
import os
import warnings


def encrypt_bytes(data: bytes) -> bytes:
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        warnings.warn(
            "cryptography is not installed; encryption degraded to plaintext.",
            RuntimeWarning,
            stacklevel=2,
        )
        return data

    key_raw = os.environ.get("CHAINGUARD_ENCRYPTION_KEY", "")
    if not key_raw:
        warnings.warn(
            "CHAINGUARD_ENCRYPTION_KEY is not set; encryption degraded to plaintext.",
            RuntimeWarning,
            stacklevel=2,
        )
        return data
    return Fernet(_derive_fernet_key(key_raw)).encrypt(data)


def decrypt_bytes(data: bytes) -> bytes:
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        warnings.warn(
            "cryptography is not installed; decryption degraded to passthrough.",
            RuntimeWarning,
            stacklevel=2,
        )
        return data

    key_raw = os.environ.get("CHAINGUARD_ENCRYPTION_KEY", "")
    if not key_raw:
        warnings.warn(
            "CHAINGUARD_ENCRYPTION_KEY is not set; decryption degraded to passthrough.",
            RuntimeWarning,
            stacklevel=2,
        )
        return data
    return Fernet(_derive_fernet_key(key_raw)).decrypt(data)


def _derive_fernet_key(key_raw: str) -> bytes:
    digest = hashlib.sha256(key_raw.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)
