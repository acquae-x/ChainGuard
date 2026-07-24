from pathlib import Path

from scripts.evaluate_confidence_and_challenger import run
from src.audit import approval_required
from src.challenger import challenge_recommendation
from src.decision_confidence import ConfidenceCalibrator, raw_confidence


HISTORY_CSV = Path(__file__).resolve().parents[1] / "demo_assets" / "enterprise" / "csv" / "historical_decisions.csv"


def test_confidence_uses_pre_outcome_fields_only():
    decision = {"selected_strategy": "双供应商分单", "predicted_delay_hours": 12, "predicted_cost": 200_000}
    altered_outcome = {**decision, "outcome_status": "failed", "actual_cost": 999_999, "actual_delay_hours": 999}
    assert raw_confidence(decision) == raw_confidence(altered_outcome)


def test_calibrator_produces_explicit_calibrated_confidence():
    calibrator = ConfidenceCalibrator().fit([
        {"selected_strategy": "备用供应商", "outcome_status": "success"},
        {"selected_strategy": "紧急全量空运", "outcome_status": "failed"},
    ])
    assessment = calibrator.assess({"final_strategy": "备用供应商"})
    assert assessment["calibration_status"] == "calibrated"
    assert 0.0 <= assessment["confidence"] <= 1.0
    assert assessment["calibration_sample_size"] == 2


def test_challenger_identifies_multiple_independent_objections():
    result = challenge_recommendation(
        {"proposal_title": "full air freight", "parameters": {"supplier_ids": ["S-1"], "estimated_cost": 120}},
        {
            "requires_backup_supplier": True,
            "constraints": {"max_budget": 100},
            "historical_failure_patterns": [{"strategy_marker": "full air freight", "failure_mode": "margin loss"}],
        },
    )
    assert result["requires_manual_review"] is True
    assert {item["code"] for item in result["findings"]} == {
        "missing_backup_supplier", "hard_budget_violation", "historical_failure_pattern",
    }


def test_challenger_finding_requires_a_human_approval():
    assert approval_required({
        "inventory_risk": {"inventory_risk_index": 0},
        "debate_result": {"converged": True},
        "constraint_analysis": {"feasible_count": 1},
        "rebuttal": {"challenger": {"requires_manual_review": True}},
    }) is True


def test_experiment_writes_reliability_diagram_and_seed_measurement(tmp_path):
    report = run(HISTORY_CSV, tmp_path / "report.json", tmp_path / "reliability.svg")
    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "reliability.svg").exists()
    assert report["protocol"]["holdout_count"] > 0
    assert report["confidence"]["reliability_bins"]
    assert report["challenger"]["captured_count"] == 8
    assert report["challenger"]["well_formed_control_challenged"] is False
