import uuid
from pathlib import Path

from src.agents import generate_all_proposals
from src.arbitrator import arbitrate
from src.config_loader import load_risk_weights, load_thresholds
from src.conflict_detector import detect_conflict
from src.data_loader import load_demo_context
from src.debate import generate_rebuttal
from src.learning import (
    generate_experience_card,
    load_experience_cards,
    save_experience_card,
    search_similar_experiences,
)
from src.scoring import attach_total_scores


RUNTIME_TMP = Path(__file__).parent / "_runtime_tmp"


def _runtime_path(name: str) -> Path:
    RUNTIME_TMP.mkdir(parents=True, exist_ok=True)
    stem = Path(name).stem
    suffix = Path(name).suffix
    return RUNTIME_TMP / f"{stem}_{uuid.uuid4().hex}{suffix}"


def _proposal_by_agent(proposals, keyword):
    for proposal in proposals:
        if keyword in proposal["agent_name"]:
            return proposal
    raise AssertionError(f"missing proposal: {keyword}")


def _fixed_case_card():
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
    arbitration = arbitrate(proposals, conflict, rebuttal, context)
    return generate_experience_card(context, proposals, arbitration)


def test_generate_experience_card_fixed_case_content():
    card = _fixed_case_card()

    assert card["scenario"] == "台风导致宁波港暂停作业 导致 SUP-A 受影响，库存支撑约 36 小时"
    assert "库存可支撑时间 ≤ 36 小时" in card["trigger_conditions"]
    assert "安全库存缺口 2600 件" in card["trigger_conditions"]
    assert card["failed_reason"] == "如果采用全量空运，会过度关注时效，忽略订单毛利和客户分级。"
    assert card["recommended_pattern"] == "备用供应商 + 关键订单空运 + 非关键订单延期"
    assert card["parameter_note"] == "当前经验卡片基于模拟数据生成，真实落地时应结合企业历史应急结果校准。"
    assert card["confidence_score"] == 0.5
    assert card["historical_references"] == []


def test_save_and_load_experience_card():
    path = _runtime_path("learning_save_load.json")
    card = _fixed_case_card()

    result = save_experience_card(card, path)
    loaded = load_experience_cards(path)

    assert result["saved_count"] == 1
    assert loaded == [card]


def test_save_experience_card_replaces_same_case_id():
    path = _runtime_path("learning_replace.json")
    card = _fixed_case_card()
    save_experience_card(card, path)
    updated = {**card, "improvement_strategy": "更新后的策略"}
    save_experience_card(updated, path)

    loaded = load_experience_cards(path)

    assert len(loaded) == 1
    assert loaded[0]["improvement_strategy"] == "更新后的策略"


def test_search_similar_experiences_by_keyword():
    path = _runtime_path("learning_search.json")
    card = _fixed_case_card()
    save_experience_card(card, path)

    matches = search_similar_experiences("宁波港暂停作业", path)

    assert len(matches) == 1
    assert matches[0]["case_id"] == card["case_id"]


def test_load_experience_cards_missing_file_returns_empty_list():
    path = _runtime_path("missing.json")

    assert load_experience_cards(path) == []
