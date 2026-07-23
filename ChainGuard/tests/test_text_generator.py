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



# --------------------------------------------------------------------------
# DeepSeek 后端
#
# 安全属性与 Ollama 路径完全一致：结构不符/网络失败/缺 key 一律落模板，
# 且绝不把异常抛给决策链。这些用例就是守这条线的。
# --------------------------------------------------------------------------

def _deepseek_response(content: str):
    """构造一个 OpenAI 兼容格式的响应体。"""

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": content}}]},
                ensure_ascii=False,
            ).encode("utf-8")

    return FakeResponse


def _rebuttal_via(generator: TextGenerator) -> dict:
    return generator.generate_rebuttal_content(
        branch="high_cost",
        debater="财务 Agent",
        target="物流 Agent",
        proposal_data={"proposal_title": "高成本快速运输", "scores": {"cost": 30}},
        context_data={"event_title": "供应商停产事件", "critical_orders_count": 2},
    )


def test_provider_defaults_to_ollama_without_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("CHAINGUARD_LLM_PROVIDER", raising=False)
    assert TextGenerator().provider == "ollama"


def test_provider_switches_to_deepseek_when_key_present(monkeypatch):
    monkeypatch.delenv("CHAINGUARD_LLM_PROVIDER", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    generator = TextGenerator()
    assert generator.provider == "deepseek"
    assert generator.model == "deepseek-chat"


def test_explicit_endpoint_stays_on_ollama_even_with_key(monkeypatch):
    """既有用例用不可达 endpoint 验证模板兜底；环境里恰好有 key 时不得改走远程。"""
    monkeypatch.delenv("CHAINGUARD_LLM_PROVIDER", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    assert TextGenerator(endpoint="http://localhost:9/api/generate").provider == "ollama"


def test_env_can_force_provider(monkeypatch):
    monkeypatch.setenv("CHAINGUARD_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    assert TextGenerator().provider == "ollama"


def test_deepseek_success_marks_llm_used(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.delenv("CHAINGUARD_LLM_PROVIDER", raising=False)
    payload = json.dumps(
        {
            "rebuttal_points": ["成本偏高", "风险需分级", "资源要聚焦"],
            "suggested_revision": "分级保障",
            "accepted_tradeoff": "让渡非关键订单时效",
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _deepseek_response(payload)())

    result = _rebuttal_via(TextGenerator(provider="deepseek", api_key="sk-test"))

    assert result["llm_used"] is True
    assert result["model_name"] == "deepseek-chat"
    assert result["rebuttal_points"] == ["成本偏高", "风险需分级", "资源要聚焦"]


def test_deepseek_schema_mismatch_falls_back_to_template(monkeypatch):
    """字段类型不符（rebuttal_points 应为 list）必须落模板，不能把模型输出放行。"""
    payload = json.dumps({"rebuttal_points": "成本偏高", "suggested_revision": 1}, ensure_ascii=False)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _deepseek_response(payload)())

    result = _rebuttal_via(TextGenerator(provider="deepseek", api_key="sk-test"))

    assert result["llm_used"] is False
    assert result["model_name"] == "template"


def test_deepseek_network_failure_falls_back_to_template(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", boom)

    result = _rebuttal_via(TextGenerator(provider="deepseek", api_key="sk-test"))

    assert result["llm_used"] is False
    assert result["model_name"] == "template"


def test_deepseek_without_api_key_falls_back_to_template(monkeypatch):
    """缺 key 时不得抛异常打断决策链，只落模板。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    result = _rebuttal_via(TextGenerator(provider="deepseek", api_key=""))

    assert result["llm_used"] is False
    assert result["model_name"] == "template"


# --------------------------------------------------------------------------
# 数值一致性校验
#
# 系统对外承诺"所有数值由代码计算，LLM 绝不改数"。结构校验管不了这件事，
# 必须由 _numbers_consistent 强制。这些用例守的就是这条承诺。
#
# 实测背景：deepseek-chat 在提示词只写"不得新增数字"时，8 次调用有 7 次
# 编造阈值（"寻找成本评分不低于60的方案"），全部被本机制拦下。
# --------------------------------------------------------------------------

def test_numbers_consistent_accepts_reused_values():
    generated = {"a": "成本分值 28，时效 92", "b": ["订单数 3"]}
    assert TextGenerator._numbers_consistent(generated, "评分 28 与 92，订单 3 个") is True


def test_numbers_consistent_rejects_invented_value():
    """模型凭空写出输入里没有的阈值 60 —— 必须判失败。"""
    generated = {"suggested_revision": "建议寻找成本评分不低于60的替代方案"}
    assert TextGenerator._numbers_consistent(generated, "评分 28 与 92") is False


def test_numbers_consistent_ignores_booleans():
    """bool 是 int 的子类，但它不是业务数值，不该被当成 1/0 参与比对。"""
    assert TextGenerator._numbers_consistent({"flag": True}, "没有任何数字") is True


def test_numbers_consistent_handles_decimal_formatting():
    """28 与 28.0 是同一个数，不应因写法差异误判。"""
    assert TextGenerator._numbers_consistent({"a": "分值 28.0"}, "分值 28") is True


def test_invented_number_falls_back_with_reason(monkeypatch):
    """端到端：结构正确但数字是编的，必须落模板并标出原因。"""
    payload = json.dumps(
        {
            # 输入里只有 30，这里冒出 60 和 88
            "rebuttal_points": ["成本分值 30 偏低", "建议提升至 60", "目标 88 分"],
            "suggested_revision": "提升至 60",
            "accepted_tradeoff": "接受 88 分",
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _deepseek_response(payload)())

    result = _rebuttal_via(TextGenerator(provider="deepseek", api_key="sk-test"))

    assert result["llm_used"] is False
    assert result["model_name"] == "template"
    assert result["fallback_reason"] == "number_mismatch"


def test_schema_mismatch_reports_its_own_reason(monkeypatch):
    """两种拒绝原因要能区分，否则排查时无从下手。"""
    payload = json.dumps({"rebuttal_points": "应为数组", "suggested_revision": "x",
                          "accepted_tradeoff": "y"}, ensure_ascii=False)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _deepseek_response(payload)())

    result = _rebuttal_via(TextGenerator(provider="deepseek", api_key="sk-test"))

    assert result["fallback_reason"] == "schema_mismatch"
