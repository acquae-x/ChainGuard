from __future__ import annotations

import dataclasses
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class NotificationPayload:
    decision_id: str
    timestamp: str
    event_type: str
    inventory_risk_index: float
    human_approval_required: bool
    decision_status: str

    @classmethod
    def from_audit_entry(cls, audit_entry: dict[str, Any]) -> "NotificationPayload":
        return cls(
            decision_id=str(audit_entry.get("decision_id", "")),
            timestamp=str(audit_entry.get("timestamp", "")),
            event_type=str(audit_entry.get("event_type", "")),
            inventory_risk_index=float(audit_entry.get("inventory_risk_index", 0.0)),
            human_approval_required=bool(
                audit_entry.get("human_approval_required", False)
            ),
            decision_status=str(audit_entry.get("decision_status", "")),
        )


class Notifier(ABC):
    @abstractmethod
    def send(self, payload: NotificationPayload) -> bool:
        """Send notification. Returns True on success, False on failure."""


class MockNotifier(Notifier):
    """In-memory notifier for testing and demo. Accumulates sent payloads."""

    def __init__(self) -> None:
        self.sent: list[NotificationPayload] = []

    def send(self, payload: NotificationPayload) -> bool:
        self.sent.append(payload)
        return True


class WebhookNotifier(Notifier):
    """HTTP POST notifier. Returns False on network failure; never raises."""

    def __init__(self, url: str, timeout: int = 5) -> None:
        self.url = url
        self.timeout = timeout

    def send(self, payload: NotificationPayload) -> bool:
        try:
            import json
            import urllib.request

            data = json.dumps(dataclasses.asdict(payload), ensure_ascii=False).encode()
            request = urllib.request.Request(
                self.url,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(request, timeout=self.timeout)
            return True
        except Exception:
            return False
