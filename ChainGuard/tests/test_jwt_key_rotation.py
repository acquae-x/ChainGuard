from __future__ import annotations

import dataclasses
from datetime import timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import src.webapi.jwt_tokens as jwt_tokens
from src.webapi.config import settings, settings_from_secret_provider
from src.webapi.errors import ApiError


def _claims(token_type: str = "access") -> dict[str, object]:
    return {"sub": "rotation-test", "type": token_type}


def _settings(monkeypatch, **overrides) -> None:
    monkeypatch.setattr(jwt_tokens, "settings", dataclasses.replace(settings, **overrides))


def test_hs256_token_signed_by_previous_key_survives_rotation(monkeypatch):
    old_key = "old-jwt-signing-key-that-is-at-least-32-bytes"
    _settings(
        monkeypatch,
        jwt_algorithm="HS256",
        jwt_secret="new-jwt-signing-key-that-is-at-least-32-bytes",
        jwt_secret_previous=old_key,
    )
    old_token = jwt.encode(_claims(), old_key, algorithm="HS256")

    assert jwt_tokens.decode_typed_token(old_token, "access")["sub"] == "rotation-test"


def test_hs256_token_signed_by_removed_key_is_rejected(monkeypatch):
    removed_key = "removed-jwt-signing-key-that-is-at-least-32-bytes"
    removed_token = jwt.encode(_claims(), removed_key, algorithm="HS256")
    _settings(
        monkeypatch,
        jwt_algorithm="HS256",
        jwt_secret="new-jwt-signing-key-that-is-at-least-32-bytes",
        jwt_secret_previous=removed_key,
    )
    # Self-prove the rejection probe: this exact token is valid before its key
    # is removed, so a later 401 demonstrates removal rather than a bad fixture.
    assert jwt_tokens.decode_typed_token(removed_token, "access")["sub"] == "rotation-test"
    _settings(
        monkeypatch,
        jwt_algorithm="HS256",
        jwt_secret="new-jwt-signing-key-that-is-at-least-32-bytes",
        jwt_secret_previous="older-jwt-signing-key-that-is-at-least-32-bytes",
    )

    with pytest.raises(ApiError) as error:
        jwt_tokens.decode_typed_token(removed_token, "access")

    assert error.value.status_code == 401


def test_hs256_issuance_always_uses_current_key(monkeypatch):
    current_key = "current-jwt-signing-key-that-is-at-least-32-bytes"
    old_key = "old-jwt-signing-key-that-is-at-least-32-bytes"
    _settings(monkeypatch, jwt_algorithm="HS256", jwt_secret=current_key, jwt_secret_previous=old_key)

    token = jwt_tokens.encode_typed_token(_claims(), token_type="access", expires=timedelta(minutes=5))

    assert jwt.decode(token, current_key, algorithms=["HS256"])["sub"] == "rotation-test"
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, old_key, algorithms=["HS256"])


def test_rs256_token_signed_by_previous_public_key_survives_rotation(monkeypatch):
    old_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    new_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    old_private_pem = old_private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    old_public_pem = old_private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    new_public_pem = new_private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    _settings(
        monkeypatch,
        jwt_algorithm="RS256",
        jwt_rs256_private_key=new_private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
        jwt_rs256_public_key=new_public_pem,
        jwt_rs256_public_key_previous=old_public_pem,
    )
    old_token = jwt.encode(_claims(), old_private_pem, algorithm="RS256")

    assert jwt_tokens.decode_typed_token(old_token, "access")["sub"] == "rotation-test"


def test_settings_can_resolve_jwt_secrets_from_a_provider():
    class MappingSecretProvider:
        def get(self, name: str) -> str:
            return {"JWT_SECRET": "provider-current", "JWT_SECRET_PREVIOUS": "provider-old"}.get(name, "")

    configured = settings_from_secret_provider(MappingSecretProvider())

    assert configured.jwt_secret == "provider-current"
    assert configured.jwt_secret_previous == "provider-old"
