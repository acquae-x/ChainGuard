"""Sensitivity analysis of the coordination gain w.r.t. PayoffModel weights.

The coordination gain (optimal_system_utility - individual_system_utility) is the
headline number of the demo scenario. It is computed from eleven payoff weights
that are expert priors, not calibrated values, so the honest question is: how much
of the gain is an artifact of those eleven numbers?

Three sweeps, all deterministic:

  * ``oat``    one-at-a-time multiplicative perturbation of each weight
  * ``pair``   convex re-allocation inside each own/system utility pair
  * ``joint``  seeded Monte-Carlo perturbation of all eleven weights at once

Every run rebuilds payoffs and re-solves the 27 combinations; nothing is cached,
so a flipped optimal combination shows up as a changed label.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_risk_weights  # noqa: E402
from src.constraint_solver import ConstraintSolver  # noqa: E402
from src.data_loader import load_demo_context  # noqa: E402
from src.game_model import _PAYOFF_WEIGHTS_DEFAULTS, PayoffModel  # noqa: E402


# Each pair holds weights that act as a convex split of one utility term, so the
# meaningful perturbation is a re-allocation between them rather than an
# independent scaling of each.
CONVEX_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("procurement_own", "procurement_own_coverage", "procurement_own_speed"),
    ("procurement_sys", "procurement_sys_coverage", "procurement_sys_cost_efficiency"),
    ("logistics_own", "logistics_own_speed", "logistics_own_availability"),
    ("logistics_sys", "logistics_sys_speed", "logistics_sys_cost_efficiency"),
    ("finance_sys", "finance_sys_service", "finance_sys_own"),
)

# finance_own_scale is a lone gain factor, not half of a convex pair.
SCALAR_WEIGHTS: tuple[str, ...] = ("finance_own_scale",)

OAT_FACTORS: tuple[float, ...] = (0.50, 0.75, 0.90, 1.10, 1.25, 1.50)


def reproducible_timestamp() -> str:
    """Use SOURCE_DATE_EPOCH or the script commit time, never wall-clock time."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).isoformat()
    try:
        value = subprocess.check_output(
            [
                "git", "-C", str(PROJECT_ROOT.parent), "log", "-1",
                "--format=%cI", "--", "ChainGuard/scripts/run_payoff_sensitivity.py",
                "ChainGuard/config/risk_weights.yaml",
            ],
            text=True,
        ).strip()
        if value:
            return value
    except (OSError, subprocess.SubprocessError):
        pass
    return "1970-01-01T00:00:00+00:00"


def solve(weights: dict[str, float], context: dict[str, Any]) -> dict[str, Any]:
    """Rebuild payoffs under ``weights`` and re-solve the 27 combinations."""
    model = PayoffModel(payoff_weights=weights)
    payoffs = {
        "procurement": model.evaluate_procurement(context),
        "logistics": model.evaluate_logistics(context),
        "finance": model.evaluate_finance(context),
    }
    analysis = ConstraintSolver().solve(payoffs, context)
    individual = analysis.individual_system_utility
    optimal = analysis.optimal_system_utility
    gain = round(optimal - individual, 2)
    return {
        "individual_system_utility": individual,
        "optimal_system_utility": optimal,
        "coordination_gain": gain,
        "coordination_gain_pct": (
            round(gain / individual * 100, 1) if individual > 0 else 0.0
        ),
        "feasible_count": analysis.feasible_count,
        "optimal_combo": dict(analysis.optimal_combo),
    }


def combo_key(combo: dict[str, str]) -> str:
    return "|".join(combo[key] for key in ("procurement", "logistics", "finance"))


def run_oat(
    baseline_weights: dict[str, float],
    baseline: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in sorted(baseline_weights):
        for factor in OAT_FACTORS:
            weights = dict(baseline_weights)
            weights[name] = baseline_weights[name] * factor
            result = solve(weights, context)
            rows.append(
                {
                    "sweep": "oat",
                    "weight": name,
                    "factor": factor,
                    "value": round(weights[name], 4),
                    "combo_changed": combo_key(result["optimal_combo"])
                    != combo_key(baseline["optimal_combo"]),
                    **result,
                }
            )
    return rows


def run_pair(
    baseline_weights: dict[str, float],
    baseline: dict[str, Any],
    context: dict[str, Any],
    steps: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pair_name, left, right in CONVEX_PAIRS:
        total = baseline_weights[left] + baseline_weights[right]
        for step in range(steps + 1):
            share = step / steps
            weights = dict(baseline_weights)
            weights[left] = total * share
            weights[right] = total * (1.0 - share)
            result = solve(weights, context)
            rows.append(
                {
                    "sweep": "pair",
                    "pair": pair_name,
                    "left_weight": left,
                    "left_share": round(share, 3),
                    "left_value": round(weights[left], 4),
                    "right_value": round(weights[right], 4),
                    "combo_changed": combo_key(result["optimal_combo"])
                    != combo_key(baseline["optimal_combo"]),
                    **result,
                }
            )
    return rows


def run_joint(
    baseline_weights: dict[str, float],
    baseline: dict[str, Any],
    context: dict[str, Any],
    draws: int,
    spread: float,
    seed: int,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    for draw in range(draws):
        weights = {
            name: value * rng.uniform(1.0 - spread, 1.0 + spread)
            for name, value in baseline_weights.items()
        }
        result = solve(weights, context)
        rows.append(
            {
                "sweep": "joint",
                "draw": draw,
                "combo_changed": combo_key(result["optimal_combo"])
                != combo_key(baseline["optimal_combo"]),
                **result,
            }
        )
    return rows


def summarize(rows: list[dict[str, Any]], baseline: dict[str, Any]) -> dict[str, Any]:
    gains = [row["coordination_gain"] for row in rows]
    combos = {combo_key(row["optimal_combo"]) for row in rows}
    return {
        "runs": len(rows),
        "gain_min": min(gains),
        "gain_max": max(gains),
        "gain_mean": round(sum(gains) / len(gains), 2),
        "gain_baseline": baseline["coordination_gain"],
        "runs_with_nonpositive_gain": sum(1 for gain in gains if gain <= 0),
        "runs_with_combo_change": sum(1 for row in rows if row["combo_changed"]),
        "distinct_optimal_combos": len(combos),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sweeps",
        default="oat,pair,joint",
        help="comma-separated subset of oat,pair,joint",
    )
    parser.add_argument(
        "--baseline-only",
        action="store_true",
        help="print the baseline coordination gain and exit; runs no sweep",
    )
    parser.add_argument("--pair-steps", type=int, default=10)
    parser.add_argument("--joint-draws", type=int, default=500)
    parser.add_argument(
        "--joint-spread",
        type=float,
        default=0.50,
        help="each weight is multiplied by uniform(1-spread, 1+spread)",
    )
    parser.add_argument("--seed", type=int, default=20260727)
    parser.add_argument("--output", type=Path, help="write the full result as JSON")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    selected: set[str] = (
        set()
        if args.baseline_only
        else {name.strip() for name in args.sweeps.split(",") if name.strip()}
    )

    context = load_demo_context()
    configured = load_risk_weights().get("payoff_weights") or _PAYOFF_WEIGHTS_DEFAULTS
    baseline_weights = {
        key: float(configured[key]) for key in _PAYOFF_WEIGHTS_DEFAULTS
    }
    baseline = solve(baseline_weights, context)

    rows: list[dict[str, Any]] = []
    if "oat" in selected:
        rows += run_oat(baseline_weights, baseline, context)
    if "pair" in selected:
        rows += run_pair(baseline_weights, baseline, context, args.pair_steps)
    if "joint" in selected:
        rows += run_joint(
            baseline_weights,
            baseline,
            context,
            args.joint_draws,
            args.joint_spread,
            args.seed,
        )

    per_sweep = {
        sweep: summarize([row for row in rows if row["sweep"] == sweep], baseline)
        for sweep in sorted({row["sweep"] for row in rows})
    }

    print("baseline (config payoff_weights)")
    print(
        f"  individual={baseline['individual_system_utility']} "
        f"optimal={baseline['optimal_system_utility']} "
        f"gain={baseline['coordination_gain']} "
        f"({baseline['coordination_gain_pct']}%) "
        f"feasible={baseline['feasible_count']}/27"
    )
    print(f"  optimal_combo={combo_key(baseline['optimal_combo'])}")
    for sweep, stats in per_sweep.items():
        print(f"\n{sweep} sweep")
        for key, value in stats.items():
            print(f"  {key}: {value}")

    payload = {
        "generated_at": reproducible_timestamp(),
        "seed": args.seed,
        "baseline_weights": baseline_weights,
        "baseline": baseline,
        "summary": per_sweep,
        "rows": rows,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nwrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
