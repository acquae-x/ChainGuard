"""Run the pre-registered confidence-calibration and challenger experiment.

Usage:
    python scripts/evaluate_confidence_and_challenger.py
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.challenger import challenge_recommendation  # noqa: E402
from src.decision_confidence import (  # noqa: E402
    ConfidenceCalibrator,
    brier_score,
    raw_confidence,
    reliability_bins,
)


DEFAULT_HISTORY = PROJECT_ROOT / "demo_assets" / "enterprise" / "csv" / "historical_decisions.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / ".workspace" / "confidence-and-challenger-results.json"
DEFAULT_DIAGRAM = PROJECT_ROOT / ".workspace" / "confidence-reliability.svg"


def _records(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return sorted(csv.DictReader(handle), key=lambda row: str(row.get("created_at") or ""))


def _seed_cases() -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    return [
        ("single_supplier", {"proposal_title": "single source", "parameters": {"supplier_ids": ["S-1"]}}, {"requires_backup_supplier": True}),
        ("budget_overrun", {"parameters": {"estimated_cost": 140}}, {"constraints": {"max_budget": 100}}),
        ("coverage_shortfall", {"parameters": {"coverage_rate": 0.72}}, {"constraints": {"min_coverage_rate": 0.95}}),
        ("one_sided", {"considered_agent_roles": ["finance"]}, {"available_agent_roles": ["finance", "logistics", "procurement"]}),
        ("known_failure_pattern", {"proposal_title": "full air freight"}, {"historical_failure_patterns": [{"strategy_marker": "full air freight", "failure_mode": "margin loss"}]}),
        ("backup_and_budget", {"parameters": {"supplier_ids": ["S-1"], "estimated_cost": 125}}, {"requires_backup_supplier": True, "constraints": {"max_budget": 100}}),
        ("coverage_and_history", {"proposal_title": "defer delivery", "parameters": {"coverage_rate": 0.80}}, {"constraints": {"min_coverage_rate": 0.96}, "historical_failure_patterns": [{"strategy_marker": "defer delivery", "failure_mode": "lost A-order"}]}),
        ("one_sided_history", {"proposal_title": "spot-buy", "considered_agent_roles": ["procurement"]}, {"available_agent_roles": ["procurement", "finance"], "historical_failure_patterns": [{"strategy_marker": "spot-buy", "failure_mode": "quality escape"}]}),
    ]


def _write_svg(bins: list[dict[str, Any]], path: Path) -> None:
    width, height, margin = 680, 420, 55
    plot_width, plot_height = width - 2 * margin, height - 2 * margin
    points = []
    labels = []
    for item in bins:
        x = margin + float(item["confidence"]) * plot_width
        y = height - margin - float(item["success_rate"]) * plot_height
        points.append(f"{x:.1f},{y:.1f}")
        labels.append(f'<text x="{x:.1f}" y="{height - 25}" text-anchor="middle">{item["confidence"]:.2f}</text>')
    circle_svg = "".join(
        f'<circle cx="{point.split(",")[0]}" cy="{point.split(",")[1]}" r="5" fill="#1565c0"/>'
        for point in points
    )
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="white"/>
<text x="{margin}" y="30" font-family="sans-serif" font-size="18">Reliability diagram: calibrated confidence vs observed success</text>
<line x1="{margin}" y1="{height-margin}" x2="{width-margin}" y2="{margin}" stroke="#9e9e9e" stroke-dasharray="5 5"/>
<line x1="{margin}" y1="{height-margin}" x2="{width-margin}" y2="{height-margin}" stroke="black"/>
<line x1="{margin}" y1="{height-margin}" x2="{margin}" y2="{margin}" stroke="black"/>
<polyline points="{' '.join(points)}" fill="none" stroke="#1565c0" stroke-width="2"/>{circle_svg}
<text x="{width/2}" y="{height-5}" font-family="sans-serif" text-anchor="middle">calibrated confidence</text>
<text x="16" y="{height/2}" font-family="sans-serif" text-anchor="middle" transform="rotate(-90 16 {height/2})">observed success rate</text>
{''.join(labels)}</svg>'''
    path.write_text(svg, encoding="utf-8")


def run(history_path: Path, output_path: Path, diagram_path: Path) -> dict[str, Any]:
    records = _records(history_path)
    split = int(len(records) * 0.8)
    train, holdout = records[:split], records[split:]
    calibrator = ConfidenceCalibrator().fit(train)
    raw_pairs = [(raw_confidence(record), int(record["outcome_status"] == "success")) for record in holdout]
    calibrated_pairs = [(calibrator.calibrate(raw), outcome) for raw, outcome in raw_pairs]
    bins = [item.to_dict() for item in reliability_bins(calibrated_pairs)]
    monotonic = all(left["success_rate"] <= right["success_rate"] for left, right in zip(bins, bins[1:]))
    raw_brier = brier_score(raw_pairs)
    calibrated_brier = brier_score(calibrated_pairs)

    seed_results = []
    for name, recommendation, context in _seed_cases():
        result = challenge_recommendation(recommendation, context)
        seed_results.append({"name": name, "captured": result["requires_manual_review"], "codes": [item["code"] for item in result["findings"]]})
    captured = sum(item["captured"] for item in seed_results)
    control = challenge_recommendation(
        {
            "parameters": {"supplier_ids": ["S-1", "S-2"], "coverage_rate": 0.99, "estimated_cost": 90},
            "considered_agent_roles": ["finance", "logistics"],
        },
        {
            "requires_backup_supplier": True,
            "constraints": {"max_budget": 100, "min_coverage_rate": 0.95},
            "available_agent_roles": ["finance", "logistics"],
        },
    )
    report = {
        "protocol": {"train_count": len(train), "holdout_count": len(holdout), "split": "chronological 80/20", "success_definition": "outcome_status == success"},
        "confidence": {"raw_brier": raw_brier, "calibrated_brier": calibrated_brier, "brier_improvement": round(raw_brier - calibrated_brier, 6), "reliability_bins": bins, "monotonic_non_decreasing": monotonic},
        "challenger": {"seed_count": len(seed_results), "captured_count": captured, "capture_rate": round(captured / len(seed_results), 4), "seed_results": seed_results, "well_formed_control_challenged": control["requires_manual_review"]},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_svg(bins, diagram_path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate confidence calibration and challenger seeds.")
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--diagram", type=Path, default=DEFAULT_DIAGRAM)
    args = parser.parse_args()
    print(json.dumps(run(args.history, args.output, args.diagram), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
