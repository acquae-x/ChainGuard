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


def encryption_status() -> dict[str, Any]:
    """Read-only encryption availability probe with no encryption side effects."""
    try:
        from cryptography.fernet import Fernet  # noqa: F401

        library_available = True
    except Exception:
        library_available = False

    key_configured = bool(os.environ.get("CHAINGUARD_ENCRYPTION_KEY", "").strip())
    active = library_available and key_configured
    if not library_available:
        note = "cryptography 库缺失，当前加密能力降级为明文/透传。"
    elif not key_configured:
        note = "CHAINGUARD_ENCRYPTION_KEY 未配置，当前加密能力未启用。"
    else:
        note = "Fernet 加密已启用，密钥来自 CHAINGUARD_ENCRYPTION_KEY。"

    return {
        "library_available": library_available,
        "key_configured": key_configured,
        "active": active,
        "algorithm": "Fernet(AES-128-CBC + HMAC)",
        "note": note,
    }
