from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.drift_monitor import load_historical_decisions, run_recalibration_cycle


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one ChainGuard drift check and recalibration recommendation cycle."
    )
    parser.add_argument("--db", required=True, help="SQLite tenant database path.")
    parser.add_argument("--baseline", type=float, default=None, help="Optional baseline success rate.")
    args = parser.parse_args()

    records = load_historical_decisions(args.db)
    result = run_recalibration_cycle(records, baseline_success_rate=args.baseline)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
