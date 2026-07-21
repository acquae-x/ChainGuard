import json
import uuid
from copy import deepcopy
from pathlib import Path

import src.orchestrator as orchestrator_module
from src.arbitrator import arbitrate
from src.config_loader import load_risk_weights, load_thresholds
from src.conflict_detector import detect_conflict
from src.data_loader import load_demo_context
from src.debate import generate_rebuttal
from src.feedback import ExperienceFeedback
from src.learning import generate_experience_card, save_experience_card
from src.orchestrator import DecisionOrchestrator
from src.agents import generate_all_proposals
from src.scoring import attach_total_scores


RUNTIME_TMP = Path(__file__).parent / "_runtime_tmp"


def _runtime_path(name: str) -> Path:
    RUNTIME_TMP.mkdir(exist_ok=True)
    return RUNTIME_TMP / name


def _proposal_by_agent(proposals, keyword):
    return next(
        proposal
        for proposal in proposals
        if keyword in proposal["agent_name"]
    )


def _arbitration_payload(context):
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
    arbitration = arbitrate(proposals, conflict, rebuttal, context)
    return proposals, arbitration


def _write_cards(path: Path):
    cards = [
        {
            "case_id": "case-typhoon",
            "scenario": "typhoon_port_shutdown 台风导致宁波港暂停作业 核心控制芯片",
            "trigger_conditions": ["库存可支撑时间 ≤ 36 小时"],
            "failed_reason": "全量空运忽略成本。",
            "improvement_strategy": "采用客户分级保障。",
            "recommended_pattern": "备用供应商 + 关键订单空运 + 非关键订单延期",
            "tags": ["typhoon_port_shutdown", "核心控制芯片", "库存不足"],
        },
        {
            "case_id": "case-quality",
            "scenario": "quality_recall 供应商质量异常",
            "trigger_conditions": ["质量抽检失败"],
            "failed_reason": "缺少替代料验证。",
            "improvement_strategy": "提前维护替代料清单。",
            "recommended_pattern": "替代料验证 + 供应商整改",
            "tags": ["quality_recall", "替代料"],
        },
    ]
    path.write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")
    return cards


def test_retrieve_missing_cards_file_returns_empty_result():
    path = _runtime_path(f"t07_missing_{uuid.uuid4().hex}.json")

    result = ExperienceFeedback(path).retrieve(load_demo_context())

    assert result.references == []
    assert result.reference_count == 0
    assert result.confidence_adjustment == 0.0
    assert result.risk_hints == []


def test_retrieve_returns_matches_for_keyword_cards():
    path = _runtime_path("t07_keyword_cards.json")
    _write_cards(path)

    result = ExperienceFeedback(path).retrieve(load_demo_context())

    assert result.reference_count >= 1
    assert result.references[0].case_id == "case-typhoon"
    assert result.risk_hints


def test_similarity_score_orders_more_specific_match_first():
    path = _runtime_path("t07_ordering_cards.json")
    _write_cards(path)

    result = ExperienceFeedback(path).retrieve(load_demo_context())

    assert result.references[0].similarity_score >= result.references[-1].similarity_score


def test_confidence_adjustment_caps_at_three_references():
    path = _runtime_path("t07_confidence_cards.json")
    cards = []
    for index in range(5):
        cards.append(
            {
                "case_id": f"case-{index}",
                "scenario": "typhoon_port_shutdown 台风导致宁波港暂停作业 核心控制芯片",
                "trigger_conditions": [],
                "failed_reason": "",
                "improvement_strategy": "",
                "recommended_pattern": "分级保障",
                "tags": ["typhoon_port_shutdown"],
            }
        )
    path.write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")

    result = ExperienceFeedback(path, top_k=5).retrieve(load_demo_context())

    assert result.reference_count == 5
    assert result.confidence_adjustment == 0.3


def test_generate_experience_card_without_retrieval_has_neutral_confidence():
    context = load_demo_context()
    proposals, arbitration = _arbitration_payload(context)

    card = generate_experience_card(context, proposals, arbitration)

    assert card["confidence_score"] == 0.5
    assert card["historical_references"] == []


def test_generate_experience_card_with_retrieval_adds_references():
    path = _runtime_path("t07_card_generation_cards.json")
    _write_cards(path)
    context = load_demo_context()
    proposals, arbitration = _arbitration_payload(context)
    retrieval_result = ExperienceFeedback(path).retrieve(context)

    card = generate_experience_card(
        context,
        proposals,
        arbitration,
        retrieval_result=retrieval_result,
    )

    assert card["confidence_score"] > 0.5
    assert card["historical_references"]


def test_orchestrator_outputs_serializable_experience_references(monkeypatch):
    path = _runtime_path("t07_orchestrator_cards.json")
    _write_cards(path)

    monkeypatch.setattr(
        orchestrator_module,
        "ExperienceFeedback",
        lambda: ExperienceFeedback(path),
    )
    monkeypatch.setattr(
        orchestrator_module,
        "save_experience_card",
        lambda card: save_experience_card(card, path),
    )

    result = DecisionOrchestrator().run_demo()
    payload = result.to_dict()

    assert "experience_references" in payload
    assert json.dumps(payload["experience_references"], ensure_ascii=False)
    assert result.experience_references["reference_count"] >= 1


def test_second_run_retrieves_first_saved_experience(monkeypatch):
    path = _runtime_path("t07_second_run_cards.json")
    path.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(
        orchestrator_module,
        "ExperienceFeedback",
        lambda: ExperienceFeedback(path),
    )
    monkeypatch.setattr(
        orchestrator_module,
        "save_experience_card",
        lambda card: save_experience_card(card, path),
    )

    first = DecisionOrchestrator().run_demo()
    second = DecisionOrchestrator().run_demo()

    assert first.experience_references["reference_count"] == 0
    assert second.experience_references["reference_count"] >= 1


def test_build_query_changes_for_different_event_type():
    context = load_demo_context()
    changed = deepcopy(context)
    changed["events"][0]["event_type"] = "quality_recall"
    changed["events"][0]["title"] = "供应商质量召回"

    first = ExperienceFeedback._build_query(context)
    second = ExperienceFeedback._build_query(changed)

    assert first != second
    assert "quality_recall" in second


def test_experience_card_scenario_changes_with_current_stock():
    context = load_demo_context()
    changed = deepcopy(context)
    changed["inventory"]["current_stock"] = 7200
    proposals, arbitration = _arbitration_payload(context)

    first = generate_experience_card(context, proposals, arbitration)
    second = generate_experience_card(changed, proposals, arbitration)

    assert first["scenario"] != second["scenario"]
    assert "72 小时" in second["scenario"]
