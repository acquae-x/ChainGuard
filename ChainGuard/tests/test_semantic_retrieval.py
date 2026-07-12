import importlib
import json
import uuid
from pathlib import Path

from src.vector_store import EmbeddingStore, SimpleKeywordStore, TfidfStore, get_vector_store


RUNTIME_TMP = Path(__file__).parent / "_runtime_tmp"
EVAL_PATH = Path(__file__).resolve().parents[1] / "data" / "retrieval_eval.json"


def _runtime_path(name: str) -> Path:
    RUNTIME_TMP.mkdir(parents=True, exist_ok=True)
    stem = Path(name).stem
    suffix = Path(name).suffix
    return RUNTIME_TMP / f"{stem}_{uuid.uuid4().hex}{suffix}"


def _seed_cards() -> list[dict]:
    return [
        {
            "case_id": "case-typhoon-001",
            "scenario": "台风导致宁波港暂停作业，核心控制芯片库存不足",
            "trigger_conditions": ["库存支撑时间低于 48 小时", "港口暂停作业"],
            "failed_reason": "全量空运导致成本过高",
            "improvement_strategy": "备用供应商和关键客户分级保障",
            "recommended_pattern": "备用供应商 + 关键订单空运 + 非关键订单延期",
            "tags": ["台风", "港口", "芯片短缺", "库存不足"],
        },
        {
            "case_id": "case-quality-001",
            "scenario": "供应商质量异常触发批次召回",
            "trigger_conditions": ["抽检失败", "客户投诉上升"],
            "failed_reason": "替代料验证准备不足",
            "improvement_strategy": "提前维护替代料验证清单",
            "recommended_pattern": "替代料验证 + 供应商整改",
            "tags": ["质量异常", "召回", "替代料"],
        },
        {
            "case_id": "case-transport-001",
            "scenario": "铁路运输中断导致在途订单延误",
            "trigger_conditions": ["铁路中断", "交付窗口小于 24 小时"],
            "failed_reason": "路线切换预案不足",
            "improvement_strategy": "提前配置多式联运改线路径",
            "recommended_pattern": "公路接驳 + 多式联运改线",
            "tags": ["运输延误", "铁路中断", "多式联运"],
        },
        {
            "case_id": "case-demand-001",
            "scenario": "关键客户需求激增导致订单积压",
            "trigger_conditions": ["订单量增长超过 40%", "产能排期冲突"],
            "failed_reason": "客户优先级规则不清晰",
            "improvement_strategy": "按毛利和战略等级分级保障",
            "recommended_pattern": "关键客户优先 + 普通订单延期",
            "tags": ["需求激增", "关键客户", "订单分级"],
        },
    ]


def _write_cards(path: Path, cards: list[dict] | None = None) -> list[dict]:
    payload = cards if cards is not None else _seed_cards()
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def test_tfidf_store_returns_relevant_card_first():
    path = _runtime_path("semantic_tfidf_cards.json")
    _write_cards(path)

    results = TfidfStore(path).search("台风 港口 芯片 库存不足")

    assert results[0]["case_id"] == "case-typhoon-001"


def test_tfidf_store_empty_cards_returns_empty_list():
    path = _runtime_path("semantic_empty_cards.json")
    path.write_text("[]", encoding="utf-8")

    assert TfidfStore(path).search("台风 港口") == []


def test_tfidf_store_missing_file_returns_empty_list():
    path = _runtime_path("semantic_missing_cards.json")

    assert TfidfStore(path).search("台风 港口") == []


def test_tfidf_store_degraded_always_false():
    path = _runtime_path("semantic_degraded_cards.json")

    assert TfidfStore(path).degraded() is False


def test_embedding_store_degraded_when_transformers_absent(monkeypatch):
    original_import_module = importlib.import_module

    def fake_import_module(name, package=None):
        if name == "sentence_transformers":
            raise ImportError("blocked in test")
        return original_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    store = EmbeddingStore(_runtime_path("semantic_embedding_absent.json"))

    assert store.degraded() is True


def test_embedding_store_falls_back_to_tfidf(monkeypatch):
    path = _runtime_path("semantic_embedding_fallback.json")
    _write_cards(path)
    original_import_module = importlib.import_module

    def fake_import_module(name, package=None):
        if name == "sentence_transformers":
            raise ImportError("blocked in test")
        return original_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    results = EmbeddingStore(path).search("供应商 质量异常 替代料")

    assert results[0]["case_id"] == "case-quality-001"


def test_get_vector_store_tfidf_mode():
    path = _runtime_path("semantic_tfidf_mode.json")

    assert isinstance(get_vector_store("tfidf", path), TfidfStore)


def test_get_vector_store_keyword_backward_compat():
    path = _runtime_path("semantic_keyword_mode.json")

    assert isinstance(get_vector_store("keyword", path), SimpleKeywordStore)
    assert isinstance(get_vector_store("simple", path), SimpleKeywordStore)


def test_tfidf_ranks_more_specific_card_higher():
    path = _runtime_path("semantic_specific_cards.json")
    _write_cards(
        path,
        [
            {
                "case_id": "case-specific",
                "scenario": "台风导致港口暂停，芯片库存不足",
                "trigger_conditions": [],
                "failed_reason": "",
                "improvement_strategy": "关键订单空运",
                "recommended_pattern": "港口切换 + 芯片保供",
                "tags": ["台风", "港口", "芯片", "库存不足"],
            },
            {
                "case_id": "case-partial",
                "scenario": "台风天气影响常规运输",
                "trigger_conditions": [],
                "failed_reason": "",
                "improvement_strategy": "",
                "recommended_pattern": "关注天气预警",
                "tags": ["台风"],
            },
        ],
    )

    results = TfidfStore(path).search("台风 港口 芯片 库存不足")

    assert [result["case_id"] for result in results[:2]] == [
        "case-specific",
        "case-partial",
    ]


def test_recall_at_3_tfidf_on_eval_set():
    path = _runtime_path("semantic_eval_cards.json")
    _write_cards(path)
    eval_items = json.loads(EVAL_PATH.read_text(encoding="utf-8"))

    def recall_at_k(results, relevant_ids, k=3):
        returned_ids = {result.get("case_id") for result in results[:k]}
        return len(returned_ids & set(relevant_ids)) / max(len(relevant_ids), 1)

    store = TfidfStore(path)
    scores = [
        recall_at_k(
            store.search(item["query"]),
            item["relevant_case_ids"],
            k=3,
        )
        for item in eval_items
    ]

    assert sum(scores) / len(scores) >= 0.5
