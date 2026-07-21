import json

import pytest

from src.agents import generate_all_proposals
from src.config_loader import load_risk_weights
from src.data_loader import load_demo_context
from src.debate import generate_rebuttal
from src.scoring import attach_total_scores
from src.text_generator import TextGenerator


@pytest.fixture(autouse=True)
def force_rebuttal_template(monkeypatch):
    def raise_offline(self, prompt):
        raise RuntimeError("force deterministic template path")

    monkeypatch.setattr(TextGenerator, "_call_ollama_json", raise_offline)


def _proposal_by_agent(proposals, keyword):
    for proposal in proposals:
        if keyword in proposal["agent_name"]:
            return proposal
    raise AssertionError(f"missing proposal: {keyword}")


def test_fixed_case_finance_rebuts_logistics_full_air_freight():
    context = load_demo_context()
    proposals = attach_total_scores(
        generate_all_proposals(context),
        load_risk_weights()["decision_score_weights"],
    )
    logistics = _proposal_by_agent(proposals, "物流")
    finance = _proposal_by_agent(proposals, "财务")

    rebuttal = generate_rebuttal(logistics, finance, context)

    assert rebuttal["debater"] == "财务 Agent"
    assert rebuttal["target"] == "物流 Agent"
    assert any("成本分值" in point for point in rebuttal["rebuttal_points"])
    assert any(context["events"][0]["title"] in point for point in rebuttal["rebuttal_points"])
    assert any("A类关键订单" in point for point in rebuttal["rebuttal_points"])
    assert "分级保障" in rebuttal["suggested_revision"]


def test_default_lowest_rebuts_highest_when_no_special_rule():
    context = load_demo_context()
    highest = {
        "agent_name": "高分 Agent",
        "proposal": "综合方案",
        "scores": {"timeliness": 90},
    }
    lowest = {
        "agent_name": "低分 Agent",
        "proposal": "补充意见",
        "scores": {"timeliness": 80},
    }

    rebuttal = generate_rebuttal(lowest, highest, context)

    assert rebuttal["debater"] == "低分 Agent"
    assert rebuttal["target"] == "高分 Agent"
    assert rebuttal["rebuttal_points"]


def test_procurement_rebuts_when_backup_supplier_is_ignored():
    context = load_demo_context()
    procurement = {
        "agent_name": "采购 Agent",
        "proposal": "建议补充采购约束。",
        "scores": {"timeliness": 80},
    }
    target = {
        "agent_name": "运营 Agent",
        "proposal": "只调整库存分配，不考虑其他货源。",
        "scores": {"timeliness": 85},
    }

    rebuttal = generate_rebuttal(procurement, target, context)

    assert rebuttal["debater"] == "采购 Agent"
    assert any("备用供应商" in point for point in rebuttal["rebuttal_points"])


def test_logistics_rebuts_overly_conservative_plan():
    context = load_demo_context()
    logistics = {
        "agent_name": "物流 Agent",
        "proposal": "建议提高运输时效。",
        "scores": {"timeliness": 90},
    }
    target = {
        "agent_name": "财务 Agent",
        "proposal": "建议延期沟通并分批交付。",
        "scores": {"timeliness": 70},
    }

    rebuttal = generate_rebuttal(logistics, target, context)

    assert rebuttal["debater"] == "物流 Agent"
    assert any("违约风险" in point for point in rebuttal["rebuttal_points"])


def test_rebuttal_no_keyword_matching():
    context = load_demo_context()
    logistics = {
        "agent_name": "物流 Agent",
        "proposal": "建议全量空运以保障时效。",
        "scores": {"cost": 60, "timeliness": 90},
    }
    finance = {
        "agent_name": "财务 Agent",
        "proposal": "综合成本方案。",
        "scores": {"cost": 70, "timeliness": 80},
    }

    rebuttal = generate_rebuttal(logistics, finance, context)

    assert rebuttal.get("debater") != "财务 Agent" or "高成本运输" not in str(rebuttal)


def test_rebuttal_triggers_on_low_cost_score():
    context = load_demo_context()
    logistics = {
        "agent_name": "物流 Agent",
        "proposal": "高时效运输方案。",
        "proposal_title": "高时效运输方案",
        "scores": {"cost": 20, "timeliness": 90},
    }
    finance = {
        "agent_name": "财务 Agent",
        "proposal": "综合成本控制方案。",
        "scores": {"cost": 70},
    }

    rebuttal = generate_rebuttal(logistics, finance, context)

    assert rebuttal["debater"] == "财务 Agent"
    assert rebuttal["target"] == "物流 Agent"
    assert "分级保障" in rebuttal["suggested_revision"]


def test_rebuttal_fallback_no_scores():
    context = load_demo_context()
    lowest = {"agent_name": "低分 Agent", "proposal": "简单方案。"}
    highest = {"agent_name": "高分 Agent", "proposal": "综合方案。"}

    rebuttal = generate_rebuttal(lowest, highest, context)

    assert isinstance(rebuttal, dict)
    assert "rebuttal_points" in rebuttal
    assert len(rebuttal["rebuttal_points"]) > 0


def test_rebuttal_text_no_demo_keywords():
    context = load_demo_context()
    context["events"][0]["title"] = "供应商停产影响核心物料"
    logistics = {
        "agent_name": "物流 Agent",
        "proposal": "高时效运输方案。",
        "proposal_title": "高时效运输方案",
        "scores": {"cost": 20, "timeliness": 90},
    }
    finance = {
        "agent_name": "财务 Agent",
        "proposal": "综合成本控制方案。",
        "scores": {"cost": 70},
    }

    rebuttal = generate_rebuttal(logistics, finance, context)
    text = json.dumps(
        {
            "rebuttal_points": rebuttal["rebuttal_points"],
            "suggested_revision": rebuttal["suggested_revision"],
        },
        ensure_ascii=False,
    )

    assert "台风" not in text
    assert "全量空运" not in text


def test_rebuttal_text_uses_event_title():
    context = load_demo_context()
    context["events"][0]["title"] = "供应商停产影响核心物料"
    logistics = {
        "agent_name": "物流 Agent",
        "proposal": "高时效运输方案。",
        "proposal_title": "高时效运输方案",
        "scores": {"cost": 20, "timeliness": 90},
    }
    finance = {
        "agent_name": "财务 Agent",
        "proposal": "综合成本控制方案。",
        "scores": {"cost": 70},
    }

    rebuttal = generate_rebuttal(logistics, finance, context)

    assert any("供应商停产影响核心物料" in point for point in rebuttal["rebuttal_points"])


def test_rebuttal_branch_conditions_unchanged():
    context = load_demo_context()
    logistics = {
        "agent_name": "物流 Agent",
        "proposal": "高时效运输方案。",
        "proposal_title": "高时效运输方案",
        "scores": {"cost": 20, "timeliness": 90},
    }
    finance = {
        "agent_name": "财务 Agent",
        "proposal": "综合成本控制方案。",
        "scores": {"cost": 70},
    }

    rebuttal = generate_rebuttal(logistics, finance, context)

    assert rebuttal["debater"] == "财务 Agent"
    assert rebuttal["target"] == "物流 Agent"
    assert any("成本分值" in point for point in rebuttal["rebuttal_points"])


def test_rebuttal_result_has_all_keys():
    context = load_demo_context()
    lowest = {"agent_name": "低分 Agent", "proposal": "简单方案。"}
    highest = {"agent_name": "高分 Agent", "proposal": "综合方案。"}

    rebuttal = generate_rebuttal(lowest, highest, context)

    assert {"debater", "target", "rebuttal_points", "suggested_revision", "accepted_tradeoff"} <= set(rebuttal)
    assert isinstance(rebuttal["rebuttal_points"], list)
    assert isinstance(rebuttal["suggested_revision"], str)
    assert isinstance(rebuttal["accepted_tradeoff"], str)
