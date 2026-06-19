import pytest

from src.agents import generate_all_proposals
from src.arbitrator import arbitrate
from src.config_loader import load_risk_weights, load_thresholds
from src.conflict_detector import detect_conflict
from src.data_loader import load_demo_context
from src.debate import generate_rebuttal
from src.scoring import attach_total_scores
from src.text_generator import TextGenerator


@pytest.fixture(autouse=True)
def force_arbitration_template(monkeypatch):
    def raise_offline(self, prompt):
        raise RuntimeError("force deterministic template path")

    monkeypatch.setattr(TextGenerator, "_call_ollama_json", raise_offline)


def _minimal_context(event_type="port_shutdown", material_name="TEST-CHIP"):
    return {
        "inventory": {"material_name": material_name},
        "orders": [],
        "events": [
            {
                "event_type": event_type,
                "title": f"{event_type} 测试事件",
            }
        ],
    }


def _minimal_proposals():
    return [
        {"agent_name": "采购 Agent", "total_score": 82},
        {"agent_name": "物流 Agent", "total_score": 78},
        {"agent_name": "财务 Agent", "total_score": 80},
    ]


def _proposal_by_agent(proposals, keyword):
    for proposal in proposals:
        if keyword in proposal["agent_name"]:
            return proposal
    raise AssertionError(f"missing proposal: {keyword}")


def _fixed_case_arbitration():
    context = load_demo_context()
    proposals = attach_total_scores(
        generate_all_proposals(context),
        load_risk_weights()["decision_score_weights"],
    )
    conflict = detect_conflict(proposals, load_thresholds())
    rebuttal = generate_rebuttal(
        _proposal_by_agent(proposals, "物流"),
        _proposal_by_agent(proposals, "财务"),
        context,
    )
    return arbitrate(proposals, conflict, rebuttal, context)


def test_title_changes_with_event_type():
    port_result = arbitrate(
        _minimal_proposals(),
        {"has_conflict": False},
        {},
        _minimal_context("port_shutdown"),
    )
    supplier_result = arbitrate(
        _minimal_proposals(),
        {"has_conflict": False},
        {},
        _minimal_context("supplier_shutdown"),
    )

    assert port_result["final_decision_title"] != supplier_result["final_decision_title"]


def test_title_contains_material_name():
    result = arbitrate(
        _minimal_proposals(),
        {"has_conflict": False},
        {},
        _minimal_context(material_name="TEST-CHIP"),
    )

    assert "TEST-CHIP" in result["final_decision_title"]


def test_typhoon_event_type_matches():
    result = arbitrate(
        _minimal_proposals(),
        {"has_conflict": False},
        {},
        _minimal_context("typhoon_port_shutdown"),
    )

    assert "空运" in result["final_decision_title"]


def test_fixed_demo_score_preserved():
    context = load_demo_context()
    proposals = attach_total_scores(
        generate_all_proposals(context),
        load_risk_weights()["decision_score_weights"],
    )
    conflict = detect_conflict(proposals, load_thresholds())
    rebuttal = generate_rebuttal(
        _proposal_by_agent(proposals, "物流"),
        _proposal_by_agent(proposals, "财务"),
        context,
    )
    result = arbitrate(proposals, conflict, rebuttal, context)

    assert 0 <= result["final_score"] <= 100


def test_empty_events_uses_fallback_title():
    context = _minimal_context(material_name="FALLBACK-CHIP")
    context["events"] = []

    result = arbitrate(
        _minimal_proposals(),
        {"has_conflict": False},
        {},
        context,
    )

    assert "FALLBACK-CHIP" in result["final_decision_title"]
    assert "应急供应保障" in result["final_decision_title"]


def test_arbitration_text_no_demo_keywords():
    result = _fixed_case_arbitration()
    full_text = " ".join(
        [
            result["final_strategy"],
            *result["execution_plan"],
            *[str(value) for value in result["expected_effect"].values()],
        ]
    )

    assert "B备用供应商" not in full_text
    assert "36小时" not in full_text
    assert "66小时" not in full_text


def test_arbitration_text_uses_material_name():
    context = load_demo_context()
    material_name = context["inventory"]["material_name"]
    proposals = attach_total_scores(
        generate_all_proposals(context),
        load_risk_weights()["decision_score_weights"],
    )
    conflict = detect_conflict(proposals, load_thresholds())
    result = arbitrate(proposals, conflict, {}, context)

    execution_text = " ".join(result["execution_plan"])
    assert material_name in result["final_strategy"] or material_name in execution_text


def test_arbitration_numeric_unchanged():
    port_result = arbitrate(
        _minimal_proposals(),
        {"has_conflict": False},
        {},
        _minimal_context("port_shutdown"),
    )
    supplier_result = arbitrate(
        _minimal_proposals(),
        {"has_conflict": False},
        {},
        _minimal_context("supplier_shutdown"),
    )

    assert 0 <= port_result["final_score"] <= 100
    assert 0 <= supplier_result["final_score"] <= 100


def test_arbitration_text_uses_event_title():
    event_title = "供应商停产测试事件"
    context = _minimal_context("supplier_shutdown")
    context["events"][0]["title"] = event_title

    result = arbitrate(
        _minimal_proposals(),
        {"has_conflict": False},
        {},
        context,
    )

    assert any(event_title in item for item in result["execution_plan"])
