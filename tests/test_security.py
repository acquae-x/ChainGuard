import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.domain_models import DecisionResult
from src.security.encryption import decrypt_bytes, encrypt_bytes
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


def test_encrypt_degrades_without_lib():
    with patch.dict(sys.modules, {"cryptography": None, "cryptography.fernet": None}):
        result = encrypt_bytes(b"x")

    assert result == b"x"


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
