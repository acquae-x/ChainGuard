"""Connector abstractions for external ERP/WMS/TMS systems."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ErpConnector(ABC):
    """Abstract integration boundary for enterprise source systems."""

    @abstractmethod
    def fetch_disruption_events(self) -> list[dict[str, Any]]:
        """Fetch disruption events from the upstream system."""

    @abstractmethod
    def fetch_context(self, event_id: str) -> dict[str, Any]:
        """Fetch a ScenarioLoader-compatible decision context."""

    @abstractmethod
    def write_back_decision(self, decision: dict[str, Any]) -> bool:
        """Write a generated decision back to the upstream system."""
