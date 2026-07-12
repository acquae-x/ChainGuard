import json
import urllib.request

from src.text_generator import TextGenerator


FORBIDDEN_DEMO_KEYWORDS = ("台风", "全量空运", "B备用供应商", "36小时")


def _generator() -> TextGenerator:
    return TextGenerator(endpoint="http://localhost:9/api/generate", timeout=1)


def _sample_rebuttal() -> dict:
    return _generator().generate_rebuttal_content(
        branch="high_cost",
        debater="财务 Agent",
        target="物流 Agent",
        proposal_data={
            "proposal_title": "高成本快速运输",
            "scores": {"cost": 28, "timeliness": 92},
        },
        context_data={
            "event_title": "供应商停产事件",
            "material_name": "测试芯片",
            "critical_orders_count": 2,
        },
    )


def test_rebuttal_template_no_demo_keywords():
    result = _sample_rebuttal()
    text = json.dumps(result, ensure_ascii=False)

    for keyword in FORBIDDEN_DEMO_KEYWORDS:
        assert keyword not in text


def test_arbitration_template_uses_material_name():
    result = _generator().generate_arbitration_content(
        action_phrase="多源紧急采购 + 优先配送",
        material_name="测试芯片",
        event_title="供应商停产事件",
        critical_orders_count=3,
        top_proposals=[{"proposal_title": "多源补货"}],
        final_score=88.2,
    )

    assert "测试芯片" in result["final_strategy"]


def test_arbitration_template_uses_event_title():
    result = _generator().generate_arbitration_content(
        action_phrase="多源紧急采购 + 优先配送",
        material_name="测试芯片",
        event_title="供应商停产事件",
        critical_orders_count=3,
        top_proposals=[{"proposal_title": "多源补货"}],
        final_score=88.2,
    )

    assert "供应商停产事件" in result["execution_plan"][3]


def test_rebuttal_returns_required_keys():
    result = _sample_rebuttal()

    assert isinstance(result["rebuttal_points"], list)
    assert isinstance(result["suggested_revision"], str)
    assert isinstance(result["accepted_tradeoff"], str)


def test_arbitration_returns_required_keys():
    result = _generator().generate_arbitration_content(
        action_phrase="多源紧急采购 + 优先配送",
        material_name="测试芯片",
        event_title="供应商停产事件",
        critical_orders_count=3,
        top_proposals=[{"proposal_title": "多源补货"}],
        final_score=88.2,
    )

    assert isinstance(result["final_strategy"], str)
    assert isinstance(result["execution_plan"], list)
    assert len(result["execution_plan"]) >= 4
    assert {
        "supply_continuity",
        "delivery_risk",
        "cost_risk",
        "customer_impact",
    } <= set(result["expected_effect"])
    assert isinstance(result["rejected_opinions"], list)
    assert isinstance(result["manual_confirmation_points"], list)
    assert len(result["manual_confirmation_points"]) >= 3


def test_experience_narrative_failed_has_reason():
    result = _generator().generate_experience_narrative(
        outcome_status="failed",
        scenario_desc="供应商停产应急",
        event_title="供应商停产事件",
        strategy_desc="多源紧急采购",
    )

    assert result["failed_reason"]


def test_all_methods_offline_do_not_raise():
    generator = _generator()

    rebuttal = generator.generate_rebuttal_content(
        branch="missing_backup",
        debater="采购 Agent",
        target="物流 Agent",
        proposal_data={"proposal_title": "单一来源方案", "scores": {}},
        context_data={"event_title": "供应商停产事件"},
    )
    arbitration = generator.generate_arbitration_content(
        action_phrase="多源紧急采购",
        material_name="测试芯片",
        event_title="供应商停产事件",
        critical_orders_count=1,
        top_proposals=[],
        final_score=76.5,
    )
    experience = generator.generate_experience_narrative(
        outcome_status="partial",
        scenario_desc="供应商停产应急",
        event_title="供应商停产事件",
        strategy_desc="多源紧急采购",
    )

    assert rebuttal
    assert arbitration
    assert experience
    assert rebuttal["llm_used"] is False
    assert arbitration["llm_used"] is False
    assert experience["llm_used"] is False


def test_ollama_rebuttal_path_uses_valid_json(monkeypatch):
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "response": json.dumps(
                        {
                            "rebuttal_points": ["成本偏高", "风险需分级", "资源要聚焦"],
                            "suggested_revision": "按订单优先级拆分执行路径。",
                            "accepted_tradeoff": "接受局部时效让步。",
                        },
                        ensure_ascii=False,
                    )
                },
                ensure_ascii=False,
            ).encode("utf-8")

    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())

    result = TextGenerator(endpoint="http://example.invalid/api/generate").generate_rebuttal_content(
        branch="high_cost",
        debater="财务 Agent",
        target="物流 Agent",
        proposal_data={"proposal_title": "高成本快速运输", "scores": {"cost": 30}},
        context_data={"event_title": "供应商停产事件", "critical_orders_count": 2},
    )

    assert result["llm_used"] is True
    assert result["model_name"] == "qwen2.5"
    assert result["rebuttal_points"] == ["成本偏高", "风险需分级", "资源要聚焦"]


def test_invalid_ollama_json_falls_back(monkeypatch):
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"response": "not json"}, ensure_ascii=False).encode("utf-8")

    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())

    result = TextGenerator(endpoint="http://example.invalid/api/generate").generate_rebuttal_content(
        branch="high_cost",
        debater="财务 Agent",
        target="物流 Agent",
        proposal_data={"proposal_title": "高成本快速运输", "scores": {"cost": 30}},
        context_data={"event_title": "供应商停产事件", "critical_orders_count": 2},
    )

    assert result["llm_used"] is False
    assert result["model_name"] == "template"

