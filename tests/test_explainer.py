import copy
import json
import urllib.error
import urllib.request

from src.explainer import DecisionExplainer, ExplanationResult
from src.orchestrator import DecisionOrchestrator


def _sample_result():
    return {
        "proposals": [
            {"agent_name": "采购 Agent", "action": "应急最大化供给", "total_score": 82.5},
            {"agent_name": "物流 Agent", "action": "最快运输优先", "total_score": 74.0},
        ],
        "arbitration": {"final_decision_title": "关键订单空运 + 备用供应商补货"},
        "debate_result": {
            "total_rounds": 2,
            "strategies_updated": ["procurement"],
            "system_utility_before": 183.09,
            "system_utility_after": 186.85,
        },
        "constraint_analysis": {
            "feasible_count": 5,
            "optimal_system_utility": 200.5,
        },
    }


def test_template_arbitration_summary_contains_proposal_name():
    explanation = DecisionExplainer._template_result(_sample_result())

    assert "应急最大化供给" in explanation.arbitration_summary
    assert "82.50" in explanation.arbitration_summary


def test_template_debate_narrative_contains_utility_values():
    explanation = DecisionExplainer._template_result(_sample_result())

    assert "183.09" in explanation.debate_narrative
    assert "186.85" in explanation.debate_narrative


def test_template_constraint_narrative_contains_feasible_count():
    explanation = DecisionExplainer._template_result(_sample_result())

    assert "5" in explanation.constraint_narrative
    assert "200.50" in explanation.constraint_narrative


def test_explainer_llm_used_false_when_ollama_unavailable(monkeypatch):
    def raise_url_error(*args, **kwargs):
        raise urllib.error.URLError("ollama unavailable")

    monkeypatch.setattr(urllib.request, "urlopen", raise_url_error)

    explanation = DecisionExplainer(endpoint="http://example.invalid/api/generate").explain(
        _sample_result()
    )

    assert explanation.llm_used is False
    assert explanation.model_name == "template"


def test_explanation_result_is_json_serializable():
    explanation = DecisionExplainer._template_result(_sample_result())

    assert json.dumps(explanation.to_dict(), ensure_ascii=False)


def test_explain_does_not_modify_debate_result(monkeypatch):
    def raise_url_error(*args, **kwargs):
        raise urllib.error.URLError("ollama unavailable")

    monkeypatch.setattr(urllib.request, "urlopen", raise_url_error)
    payload = _sample_result()
    before = copy.deepcopy(payload["debate_result"])

    DecisionExplainer().explain(payload)

    assert payload["debate_result"] == before


def test_explain_does_not_modify_constraint_analysis(monkeypatch):
    def raise_url_error(*args, **kwargs):
        raise urllib.error.URLError("ollama unavailable")

    monkeypatch.setattr(urllib.request, "urlopen", raise_url_error)
    payload = _sample_result()
    before = copy.deepcopy(payload["constraint_analysis"])

    DecisionExplainer().explain(payload)

    assert payload["constraint_analysis"] == before


def test_orchestrator_result_has_explanation_field():
    payload = DecisionOrchestrator().run_demo().to_dict()

    assert "explanation" in payload


def test_explanation_field_has_required_keys():
    explanation = DecisionOrchestrator().run_demo().to_dict()["explanation"]

    assert {
        "arbitration_summary",
        "debate_narrative",
        "constraint_narrative",
        "llm_used",
        "model_name",
    } <= set(explanation)


def test_llm_partial_response_uses_template_for_missing_sections(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {"response": "仲裁：LLM 解释了仲裁。"},
                ensure_ascii=False,
            ).encode("utf-8")

    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())

    explanation = DecisionExplainer(endpoint="http://example.invalid/api/generate").explain(
        _sample_result()
    )

    assert isinstance(explanation, ExplanationResult)
    assert explanation.llm_used is True
    assert explanation.arbitration_summary == "LLM 解释了仲裁。"
    assert "183.09" in explanation.debate_narrative
    assert "200.50" in explanation.constraint_narrative
