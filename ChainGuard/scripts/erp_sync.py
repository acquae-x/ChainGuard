"""Pull ERP disruptions, generate decisions, and write results back."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.connectors import RestErpConnector  # noqa: E402
from src.domain_models import DecisionResult  # noqa: E402
from src.orchestrator import DecisionOrchestrator  # noqa: E402


LOGGER = logging.getLogger(__name__)


def build_decision_payload(event_id: str, result: DecisionResult) -> dict[str, Any]:
    arbitration = result.arbitration
    return {
        "decision_id": f"DEC-{event_id}-{uuid4().hex[:8]}",
        "event_id": event_id,
        "optimal_combo": arbitration.get("final_decision_title"),
        "decision_status": "generated",
        "human_approval_required": bool(
            result.conflict.get("has_conflict")
            or result.inventory_risk.get("risk_level") in {"high", "critical"}
        ),
        "final_score": arbitration.get("final_score"),
        "execution_plan": arbitration.get("execution_plan"),
        "expected_effect": arbitration.get("expected_effect"),
    }


def run_sync(base_url: str, limit: int) -> tuple[int, int, int]:
    connector = RestErpConnector(base_url)
    events = connector.fetch_disruption_events()
    print(f"Fetched events: {len(events)}")
    if limit > 0:
        events = events[:limit]

    orchestrator = DecisionOrchestrator()
    generated_count = 0
    written_count = 0
    failed_write_count = 0

    for event in events:
        event_id = event.get("event_id")
        if not event_id:
            LOGGER.warning("Skipping event without event_id: %s", event)
            continue
        try:
            result = orchestrator.run_scenario(str(event_id), connector)
            generated_count += 1
        except Exception as exc:
            LOGGER.exception("Decision generation failed for %s: %s", event_id, exc)
            continue

        decision = build_decision_payload(str(event_id), result)
        if connector.write_back_decision(decision):
            written_count += 1
        else:
            failed_write_count += 1

    print(f"Generated decisions: {generated_count}")
    print(f"Successful write-backs: {written_count}")
    print(f"Failed write-backs: {failed_write_count}")
    return generated_count, written_count, failed_write_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--limit", type=int, default=5, help="Maximum events to sync; <=0 means all.")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))
    run_sync(args.base_url, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
