import json

from src.benchmark import run_ablation, run_baseline, run_failure_case


def test_baseline_returns_required_keys():
    result = run_baseline()

    assert {
        "inventory_risk_index",
        "feasible_count",
        "debate_converged",
        "human_approval",
        "decision_status",
        "top_proposal",
    } <= set(result)


def test_baseline_fixed_demo_values():
    result = run_baseline()

    assert 0 <= result["inventory_risk_index"] <= 100
    assert result["feasible_count"] == 27
    assert result["debate_converged"] is True
    assert result["human_approval"] is False
    assert result["decision_status"] == "ok"


def test_baseline_is_json_serializable():
    assert json.dumps(run_baseline(), ensure_ascii=False)


def test_ablation_returns_four_rows():
    assert len(run_ablation()) == 4


def test_ablation_low_stock_triggers_approval():
    low_stock = {
        row["scenario"]: row
        for row in run_ablation()
    }["low_stock_current_stock_720"]

    assert low_stock["inventory_risk_index"] > 80
    assert low_stock["human_approval"] is True


def test_ablation_no_converge_triggers_approval():
    no_converge = {
        row["scenario"]: row
        for row in run_ablation()
    }["debate_not_converged"]

    assert no_converge["human_approval"] is True
    assert no_converge["decision_status"] == "ok"


def test_ablation_without_retrieval_keeps_decision_ok():
    no_retrieval = {
        row["scenario"]: row
        for row in run_ablation()
    }["without_experience_retrieval"]

    assert no_retrieval["decision_status"] == "ok"
    assert no_retrieval["human_approval"] is False
    assert "reference_count=0" in no_retrieval["note"]


def test_ablation_without_retrieval_experience_fields_are_zero():
    no_retrieval = {
        row["scenario"]: row
        for row in run_ablation()
    }["without_experience_retrieval"]

    assert no_retrieval["experience_reference_count"] == 0
    assert no_retrieval["experience_confidence"] == 0.0


def test_ablation_baseline_experience_fields_typed():
    baseline = {
        row["scenario"]: row
        for row in run_ablation()
    }["baseline_all_modules"]

    assert "experience_reference_count" in baseline
    assert "experience_confidence" in baseline
    assert isinstance(baseline["experience_reference_count"], int)
    assert isinstance(baseline["experience_confidence"], float)


def test_failure_case_records_error():
    result = run_failure_case()

    assert result["triggered_error"] is True
    assert result["error_type"] == "ValueError"
    assert result["audit_status"] == "error"
    assert result["error_in_message"] is True


def test_failure_case_is_json_serializable():
    assert json.dumps(run_failure_case(), ensure_ascii=False)
