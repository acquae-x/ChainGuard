"""Reproduce the time-holdout check for the legacy Pearson weight suggestion.

This is an experiment, not a production promotion path.  It keeps generated
SQLite and registry files under ``.workspace/`` and never writes ``config/``.
The historical CSV has immutable outcome labels, so the script reports the
observed outcome rate for both recalculated policies and explicitly identifies
when that rate cannot be a counterfactual policy-success metric.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_risk_weights, load_thresholds  # noqa: E402
from src.parameter_calibration import (  # noqa: E402
    calibrate_inventory_risk_weights,
    evaluate_decision_outcomes,
)


WEIGHT_KEYS = (
    "shortage_urgency",
    "order_importance",
    "transit_delay",
    "external_event",
)
DEFAULT_INPUT = PROJECT_ROOT / "demo_assets" / "enterprise" / "csv" / "historical_decisions.csv"
DEFAULT_AUDIT = PROJECT_ROOT / "data" / "audit_log.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / ".workspace" / "experiments" / "calibration-outcome-loop" / "latest"


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_sqlite(rows: list[dict[str, str]], path: Path) -> None:
    """Build an isolated copy accepted by ``run_recalibration.py``."""
    if not rows:
        raise ValueError("historical-decision input is empty")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    columns = list(rows[0])
    names = ", ".join(f'"{name}" TEXT' for name in columns)
    placeholders = ", ".join("?" for _ in columns)
    connection = sqlite3.connect(path)
    try:
        connection.execute(f"CREATE TABLE historical_decisions ({names})")
        connection.executemany(
            f"INSERT INTO historical_decisions VALUES ({placeholders})",
            [[row.get(column, "") for column in columns] for row in rows],
        )
        connection.commit()
    finally:
        connection.close()


def _risk_index(record: dict[str, Any], weights: dict[str, float]) -> float:
    """Legacy proxy used by the Pearson calibrator's trigger calculation.

    All four inputs are outcome-era fields in this CSV.  This is deliberately
    retained so the experiment measures the exact legacy mechanism, while the
    report makes the resulting target leakage explicit.
    """
    coverage = float(record.get("covered_demand_rate", 0.5))
    delay = float(record.get("actual_delay_hours", 0.0))
    lost_orders = float(record.get("lost_orders", 0.0))
    downtime = float(record.get("production_downtime_hours", 0.0))
    factors = {
        "shortage_urgency": max(0.0, min((1.0 - coverage) * 100.0, 100.0)),
        "order_importance": lost_orders / (lost_orders + 1.0) * 100.0,
        "transit_delay": max(0.0, min(delay / 72.0 * 100.0, 100.0)),
        "external_event": max(0.0, min(downtime / 168.0 * 100.0, 100.0)),
    }
    return sum(float(weights[name]) * factors[name] for name in WEIGHT_KEYS)


def _recompute_holdout(
    rows: list[dict[str, str]], weights: dict[str, float], trigger: float
) -> dict[str, Any]:
    recalculated = []
    action_counts: Counter[str] = Counter()
    risk_indices: list[float] = []
    for row in rows:
        risk = _risk_index(row, weights)
        action = "escalate" if risk >= trigger else "monitor"
        action_counts[action] += 1
        risk_indices.append(risk)
        recalculated.append({**row, "recalculated_risk_index": risk, "recalculated_action": action})

    observed = evaluate_decision_outcomes(recalculated)
    return {
        "parameter_calibration": {
            "sample_size": observed["sample_size"],
            "success_rate": observed["success_rate"],
        },
        "recalculated_actions": dict(sorted(action_counts.items())),
        "mean_recalculated_risk_index": round(sum(risk_indices) / len(risk_indices), 4),
        "min_recalculated_risk_index": round(min(risk_indices), 4),
        "max_recalculated_risk_index": round(max(risk_indices), 4),
    }


def _audit_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    fields = set().union(*(row.keys() for row in rows)) if rows else set()
    return {
        "path": str(path),
        "exists": True,
        "sha256": _sha256(path),
        "rows": len(rows),
        "has_case_id": "case_id" in fields,
        "has_outcome_status": "outcome_status" in fields,
        "fields": sorted(fields),
    }


def _weights_only(weights: dict[str, Any]) -> dict[str, float]:
    return {name: float(weights[name]) for name in WEIGHT_KEYS}


def _write_report(path: Path, result: dict[str, Any]) -> None:
    current = result["holdout"]["expert"]
    suggested = result["holdout"]["suggested"]
    delta = suggested["parameter_calibration"]["success_rate"] - current["parameter_calibration"]["success_rate"]
    report = f"""# Pearson recalibration outcome-loop experiment

## Prediction recorded before execution

The preregistered prediction is in `../prediction.md`: suggested weights would
improve the chronological holdout observed success rate by at least **5.0
percentage points**.

## Reproduction

```powershell
python scripts/evaluate_calibration_outcome_loop.py
```

The script creates its SQLite input and model registry in this experiment
directory, then invokes `scripts/run_recalibration.py` once with `--registry`.
It does not modify `config/`.

## Data and split

- historical-decision input: `{result['input']['path']}`
- input SHA-256: `{result['input']['sha256']}`
- chronological split: first {result['split']['train_rows']} rows train, final {result['split']['holdout_rows']} rows holdout
- train end: `{result['split']['train_end']}`; holdout start: `{result['split']['holdout_start']}`
- audit file: `{result['audit']['path']}` ({result['audit'].get('rows', 0)} rows)
- audit joinability: `case_id={result['audit'].get('has_case_id')}`, `outcome_status={result['audit'].get('has_outcome_status')}`

The requested `data/` audit log is present, but it has neither `case_id` nor
`outcome_status`; it cannot link a decision to an outcome or identify the result
of a counterfactual strategy. The historical decision source is the repository's
offline enterprise demo CSV, so this is not production evidence.

## One isolated recalibration cycle

- current YAML weights: `{json.dumps(result['current_yaml_weights'], ensure_ascii=False)}`
- whole-data CLI Pearson suggestion: `{json.dumps(result['cli_cycle']['suggested_weights'], ensure_ascii=False)}`
- CLI output: `cycle.json`; isolated database: `historical_decisions.sqlite`; isolated registry: `model_registry.jsonl`

The whole-data suggestion proves the CLI cycle ran, but is excluded from the
holdout choice because it includes the holdout labels.

## Time-holdout comparison

- train-only Pearson suggestion: `{json.dumps(result['train_suggested_weights'], ensure_ascii=False)}`
- fixed current trigger: `{result['trigger']}`

| Policy used to recalculate holdout risk | `parameter_calibration` success rate | Recalculated actions | Mean proxy risk |
| --- | ---: | --- | ---: |
| Current YAML weights | {current['parameter_calibration']['success_rate']:.2%} | {json.dumps(current['recalculated_actions'], ensure_ascii=False)} | {current['mean_recalculated_risk_index']:.4f} |
| Train-only Pearson suggestion | {suggested['parameter_calibration']['success_rate']:.2%} | {json.dumps(suggested['recalculated_actions'], ensure_ascii=False)} | {suggested['mean_recalculated_risk_index']:.4f} |

Observed difference: **{delta:+.2%}** ({delta * 100:+.2f} percentage points).

## Result: negative / not adoptable

The prediction is falsified: the observed difference does not meet +5.0 points.
More importantly, this is not an estimate of the alternative policy's success:
`parameter_calibration.evaluate_decision_outcomes()` counts the immutable logged
`outcome_status` labels and does not consume either recalculated risk or action.
Thus it necessarily returns the same observed success rate for both policies.
In this holdout, the proxy risks differ but both stay below the fixed trigger
(expert max {current['max_recalculated_risk_index']:.2f}; suggested max
{suggested['max_recalculated_risk_index']:.2f}; trigger {result['trigger']:.2f}),
so neither policy changes a recorded action either.

One mechanism explains all observations: the legacy Pearson recommendation is
computed from outcome-era proxy fields (`actual_delay_hours`, `lost_orders`,
`production_downtime_hours`, and `covered_demand_rate`) and evaluated against
fixed logged labels. Those proxies change the score, but do not produce a
counterfactual outcome; in this split their values also remain below the fixed
trigger, so the action is unchanged. The unjoinable audit log supplies no
missing counterfactual outcome.

Therefore no `config/risk_weights.yaml` change is proposed. This experiment is
archived as a failure archaeology record, not tuned until it wins.
"""
    path.write_text(report, encoding="utf-8")


def _write_failure_archaeology(path: Path, result: dict[str, Any]) -> None:
    """Record the non-adoption decision beside the raw experiment artifacts."""
    expert = result["holdout"]["expert"]
    suggested = result["holdout"]["suggested"]
    text = f"""# Failure archaeology: Pearson outcome loop

## What was tested

The preregistered claim was that train-only Pearson weights would improve the
chronological holdout success rate by at least 5.0 percentage points. The split
contained {result['split']['train_rows']} train and {result['split']['holdout_rows']} holdout rows.

## What happened

- Expert observed success rate: {expert['parameter_calibration']['success_rate']:.2%}
- Suggested observed success rate: {suggested['parameter_calibration']['success_rate']:.2%}
- Difference: {suggested['parameter_calibration']['success_rate'] - expert['parameter_calibration']['success_rate']:+.2%}
- Both policies produced only `monitor` at the fixed {result['trigger']:.0f} trigger.

## Why this was not adopted

The legacy Pearson inputs are outcome-era fields, and the metric counts the
already logged outcome labels. The audit file has no `case_id` or
`outcome_status`, so it cannot identify the outcome that an alternative action
would have produced. This single data-generating limitation explains the score
movement without a success-rate movement and the absence of a policy-action
comparison.

## Decision

Do not modify `config/risk_weights.yaml`. A future adoption experiment needs
pre-decision features, action/assignment records, and an outcome linked to each
decision (or a prospectively randomized/approved rollout).
"""
    path.write_text(text, encoding="utf-8")


def _write_failure_archaeology(path: Path, result: dict[str, Any]) -> None:
    """Record the non-adoption decision beside the raw experiment artifacts."""
    expert = result["holdout"]["expert"]
    suggested = result["holdout"]["suggested"]
    text = f"""# Failure archaeology: Pearson outcome loop

## What was tested

The preregistered claim was that train-only Pearson weights would improve the
chronological holdout success rate by at least 5.0 percentage points. The split
contained {result['split']['train_rows']} train and {result['split']['holdout_rows']} holdout rows.

## What happened

- Expert observed success rate: {expert['parameter_calibration']['success_rate']:.2%}
- Suggested observed success rate: {suggested['parameter_calibration']['success_rate']:.2%}
- Difference: {suggested['parameter_calibration']['success_rate'] - expert['parameter_calibration']['success_rate']:+.2%}
- Both policies produced only `monitor` at the fixed {result['trigger']:.0f} trigger.

## Why this was not adopted

The legacy Pearson inputs are outcome-era fields, and the metric counts the
already logged outcome labels. The audit file has no `case_id` or
`outcome_status`, so it cannot identify the outcome that an alternative action
would have produced. This single data-generating limitation explains the score
movement without a success-rate movement and the absence of a policy-action
comparison.

## Decision

Do not modify `config/risk_weights.yaml`. A future adoption experiment needs
pre-decision features, action/assignment records, and an outcome linked to each
decision (or a prospectively randomized/approved rollout).
"""
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--audit-log", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--train-fraction", type=float, default=0.8)
    args = parser.parse_args()
    if not 0.0 < args.train_fraction < 1.0:
        raise ValueError("--train-fraction must be between 0 and 1")

    input_csv = args.input_csv.resolve()
    audit_log = args.audit_log.resolve()
    output_dir = args.output_dir.resolve()
    rows = sorted(_load_csv(input_csv), key=lambda row: row["created_at"])
    split_at = int(len(rows) * args.train_fraction)
    # A timestamp is an indivisible time bucket: never train on one row from a
    # timestamp while validating on another row from that same timestamp.
    cutoff = rows[split_at - 1]["created_at"]
    train = [row for row in rows if row["created_at"] <= cutoff]
    holdout = [row for row in rows if row["created_at"] > cutoff]
    if not train or not holdout:
        raise ValueError("time split produced an empty train or holdout partition")

    output_dir.mkdir(parents=True, exist_ok=True)
    database = output_dir / "historical_decisions.sqlite"
    registry = output_dir / "model_registry.jsonl"
    _write_sqlite(rows, database)
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "run_recalibration.py"),
            "--db",
            str(database),
            "--registry",
            str(registry),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    cli_cycle = json.loads(completed.stdout)
    (output_dir / "cycle.json").write_text(json.dumps(cli_cycle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    expert = _weights_only(load_risk_weights()["inventory_risk_weights"])
    suggested = _weights_only(calibrate_inventory_risk_weights(train))
    trigger = float(load_thresholds()["inventory_warning"]["inventory_risk_trigger"])
    result = {
        "input": {"path": str(input_csv), "sha256": _sha256(input_csv), "rows": len(rows)},
        "audit": _audit_summary(audit_log),
        "split": {
            "train_rows": len(train),
            "holdout_rows": len(holdout),
            "train_end": train[-1]["created_at"],
            "holdout_start": holdout[0]["created_at"],
        },
        "current_yaml_weights": expert,
        "cli_cycle": {"suggested_weights": _weights_only(cli_cycle["suggestions"]["risk_weight_suggestions"])},
        "train_suggested_weights": suggested,
        "trigger": trigger,
        "holdout": {
            "expert": _recompute_holdout(holdout, expert, trigger),
            "suggested": _recompute_holdout(holdout, suggested, trigger),
        },
    }
    (output_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_report(output_dir / "report.md", result)
    _write_failure_archaeology(output_dir / "failure_archaeology.md", result)
    _write_failure_archaeology(output_dir / "failure_archaeology.md", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
