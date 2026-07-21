import base64
import hashlib
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.domain_models import DecisionResult
from src.security.encryption import (
    EncryptionUnavailable,
    decrypt_bytes,
    encrypt_bytes,
    encryption_status,
    needs_rewrap,
)
from src.security.masking import mask_payload


SAMPLE_PAYLOAD = {
    "supplier_name": "Supplier ABC",
    "customer_name": "Customer XYZ",
    "amount": 50000,
    "cost": 8000,
    "status": "ok",
    "decision_id": "D-001",
}


def _mock_result() -> DecisionResult:
    return DecisionResult(
        risk_weights={},
        thresholds={},
        context={
            "events": [{"supplier_name": "Nested Supplier", "amount": 120000}],
        },
        inventory_risk={"inventory_risk_index": 75.0, "warning_level": "yellow"},
        proposals=[{"vendor_name": "Vendor A", "unit_price": 88.8}],
        conflict={},
        rebuttal={},
        arbitration={},
        experience_card={},
        constraint_analysis={},
        debate_result={},
        experience_references={},
        explanation={},
        audit_entry={
            "decision_status": "ok",
            "supplier_name": "Audit Supplier",
        },
    )


def test_mask_hides_sensitive_for_non_admin():
    result = mask_payload(SAMPLE_PAYLOAD, role="viewer")

    assert result["supplier_name"] != "Supplier ABC"
    assert result["amount"] != 50000
    assert result["status"] == "ok"
    assert result["decision_id"] == "D-001"


def test_mask_admin_sees_full():
    result = mask_payload(SAMPLE_PAYLOAD, role="admin")

    assert result == SAMPLE_PAYLOAD
    assert result is not SAMPLE_PAYLOAD


def test_mask_recurses_nested_dicts_and_lists():
    payload = {
        "outer": [
            {"supplier_name": "Supplier Nested", "lines": [{"amount": 25000}]},
            {"safe": "visible"},
        ],
    }

    result = mask_payload(payload, role="viewer")

    assert result["outer"][0]["supplier_name"] == "***"
    assert result["outer"][0]["lines"][0]["amount"] == "1-10万"
    assert result["outer"][1]["safe"] == "visible"
    assert payload["outer"][0]["supplier_name"] == "Supplier Nested"


def test_encrypt_roundtrip(monkeypatch):
    pytest.importorskip("cryptography")
    monkeypatch.setenv("CHAINGUARD_ENCRYPTION_KEY", "test-secret")

    encrypted = encrypt_bytes(b"hello")

    assert encrypted != b"hello"
    assert decrypt_bytes(encrypted) == b"hello"


def test_encrypt_fails_closed_without_lib():
    """契约变更：库缺失时抛异常，不再返回明文。旧行为会让明文静默落库。"""
    with patch.dict(sys.modules, {"cryptography": None, "cryptography.fernet": None}):
        with pytest.raises(EncryptionUnavailable):
            encrypt_bytes(b"x")


def test_encrypt_fails_closed_without_key(monkeypatch):
    monkeypatch.delenv("CHAINGUARD_ENCRYPTION_KEY", raising=False)

    with pytest.raises(EncryptionUnavailable):
        encrypt_bytes(b"x")
    with pytest.raises(EncryptionUnavailable):
        decrypt_bytes(b"cgenc:v2:whatever")


def test_v1_legacy_ciphertext_still_decrypts(monkeypatch):
    """存量密文无前缀、用裸 sha256 派生。换 KDF 后必须仍能读出来，否则升级即数据丢失。"""
    pytest.importorskip("cryptography")
    from cryptography.fernet import Fernet

    monkeypatch.setenv("CHAINGUARD_ENCRYPTION_KEY", "legacy-key")
    legacy_key = base64.urlsafe_b64encode(hashlib.sha256(b"legacy-key").digest())
    legacy_ciphertext = Fernet(legacy_key).encrypt(b"erp-token")

    assert not legacy_ciphertext.startswith(b"cgenc:v2:")
    assert decrypt_bytes(legacy_ciphertext) == b"erp-token"
    assert needs_rewrap(legacy_ciphertext) is True
    # 重新加密后带 v2 前缀，且不再需要升级
    rewrapped = encrypt_bytes(b"erp-token")
    assert rewrapped.startswith(b"cgenc:v2:")
    assert needs_rewrap(rewrapped) is False
    assert decrypt_bytes(rewrapped) == b"erp-token"


def test_real_fernet_key_bypasses_kdf(monkeypatch):
    pytest.importorskip("cryptography")
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("CHAINGUARD_ENCRYPTION_KEY", key)

    assert encryption_status()["key_derivation"] == "fernet-key"
    assert decrypt_bytes(encrypt_bytes(b"secret")) == b"secret"


def test_key_rotation_reads_previous_key(monkeypatch):
    """轮换契约：新密钥加密、旧密钥仍可解密，换密钥不需要停机回填。"""
    pytest.importorskip("cryptography")
    monkeypatch.setenv("CHAINGUARD_ENCRYPTION_KEY", "old-key")
    old_ciphertext = encrypt_bytes(b"rotate-me")

    monkeypatch.setenv("CHAINGUARD_ENCRYPTION_KEY", "new-key")
    monkeypatch.setenv("CHAINGUARD_ENCRYPTION_KEY_PREVIOUS", "old-key")

    assert decrypt_bytes(old_ciphertext) == b"rotate-me"
    assert encryption_status()["rotation_keys"] == 1
    # 新写入的密文，撤掉旧密钥后照样能读——说明加密用的是主密钥
    fresh = encrypt_bytes(b"rotate-me")
    monkeypatch.delenv("CHAINGUARD_ENCRYPTION_KEY_PREVIOUS")
    assert decrypt_bytes(fresh) == b"rotate-me"


def test_decision_response_masked_for_non_admin():
    with patch("src.api._API_KEYS", {"operator-key": "operator"}), patch(
        "src.api.DecisionOrchestrator"
    ) as mock_orch:
        mock_orch.return_value.run_demo.return_value = _mock_result()
        client = TestClient(app)
        resp = client.post("/decisions/demo", headers={"X-API-Key": "operator-key"})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["context"]["events"][0]["supplier_name"] == "***"
    assert payload["proposals"][0]["vendor_name"] == "***"
    assert payload["audit_entry"]["supplier_name"] == "***"
