from src.audit import RISK_APPROVAL_THRESHOLD, approval_required
from src.automation_stats import summarize_automation


def _entry(
    *,
    human_approval_required: bool,
    inventory_risk_index: float = 10.0,
    debate_converged: bool = True,
    constraint_feasible_count: int = 1,
) -> dict:
    return {
        "human_approval_required": human_approval_required,
        "inventory_risk_index": inventory_risk_index,
        "debate_converged": debate_converged,
        "constraint_feasible_count": constraint_feasible_count,
    }


def _approval_payload(*, risk_index: float) -> dict:
    return {
        "inventory_risk": {"inventory_risk_index": risk_index},
        "debate_result": {"converged": True},
        "constraint_analysis": {"feasible_count": 1},
    }


def test_summary_counts_auto_and_escalated():
    summary = summarize_automation(
        [
            _entry(human_approval_required=False),
            _entry(human_approval_required=False),
            _entry(human_approval_required=False),
            _entry(human_approval_required=True),
            _entry(human_approval_required=True),
        ]
    )

    assert summary.auto_approved == 3
    assert summary.escalated == 2
    assert summary.total == 5


def test_automation_rate_computed():
    summary = summarize_automation(
        [
            _entry(human_approval_required=False),
            _entry(human_approval_required=False),
            _entry(human_approval_required=False),
            _entry(human_approval_required=True),
            _entry(human_approval_required=True),
        ]
    )

    assert summary.automation_rate == 0.6
    assert summary.escalation_rate == 0.4


def test_escalation_reason_high_risk():
    summary = summarize_automation(
        [
            _entry(
                human_approval_required=True,
                inventory_risk_index=RISK_APPROVAL_THRESHOLD + 10,
            )
        ]
    )

    assert summary.escalation_reasons["高风险"] == 1


def test_escalation_reason_not_converged():
    summary = summarize_automation(
        [
            _entry(
                human_approval_required=True,
                inventory_risk_index=10,
                debate_converged=False,
            )
        ]
    )

    assert summary.escalation_reasons["辩论未收敛"] == 1
    assert "高风险" not in summary.escalation_reasons


def test_escalation_reason_infeasible():
    summary = summarize_automation(
        [
            _entry(
                human_approval_required=True,
                inventory_risk_index=10,
                constraint_feasible_count=0,
            )
        ]
    )

    assert summary.escalation_reasons["无可行解"] == 1


def test_empty_returns_zero():
    summary = summarize_automation([])

    assert summary.total == 0
    assert summary.automation_rate == 0.0


def test_input_changes_output():
    base_summary = summarize_automation(
        [
            _entry(human_approval_required=False),
            _entry(human_approval_required=False),
        ]
    )
    changed_summary = summarize_automation(
        [
            _entry(human_approval_required=False),
            _entry(human_approval_required=False),
            _entry(human_approval_required=True),
        ]
    )

    assert changed_summary.escalation_rate > base_summary.escalation_rate


def test_threshold_is_single_source():
    assert (
        approval_required(
            _approval_payload(risk_index=RISK_APPROVAL_THRESHOLD + 0.1)
        )
        is True
    )
    assert (
        approval_required(
            _approval_payload(risk_index=RISK_APPROVAL_THRESHOLD - 0.1)
        )
        is False
    )
