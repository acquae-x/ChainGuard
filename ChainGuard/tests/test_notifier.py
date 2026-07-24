from unittest.mock import patch

import pytest

from src.notifier import MockNotifier, NotificationPayload, WebhookNotifier


def _payload(decision_id: str = "D-001") -> NotificationPayload:
    return NotificationPayload(
        decision_id=decision_id,
        timestamp="2026-01-01T00:00:00",
        event_type="port_shutdown",
        inventory_risk_index=85.0,
        human_approval_required=True,
        decision_status="pending",
    )


def test_mock_notifier_send_returns_true():
    notifier = MockNotifier()
    payload = _payload()

    assert notifier.send(payload) is True
    assert len(notifier.sent) == 1


def test_mock_notifier_accumulates_multiple():
    notifier = MockNotifier()

    for i in range(3):
        notifier.send(
            NotificationPayload(
                decision_id=f"D-{i:03d}",
                timestamp="",
                event_type="",
                inventory_risk_index=0.0,
                human_approval_required=True,
                decision_status="",
            )
        )

    assert len(notifier.sent) == 3


def test_payload_from_audit_entry():
    audit = {
        "decision_id": "abc123",
        "timestamp": "2026-01-01T00:00:00",
        "event_type": "typhoon_port_shutdown",
        "inventory_risk_index": 75.5,
        "human_approval_required": True,
        "decision_status": "ok",
    }

    payload = NotificationPayload.from_audit_entry(audit)

    assert payload.decision_id == "abc123"
    assert payload.inventory_risk_index == pytest.approx(75.5)
    assert payload.human_approval_required is True


def test_webhook_notifier_returns_false_on_bad_url():
    notifier = WebhookNotifier("http://localhost:19999/nonexistent")

    with patch("urllib.request.urlopen", side_effect=OSError("connection failed")):
        result = notifier.send(_payload())

    assert result is False
