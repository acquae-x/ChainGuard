import json
import uuid
from pathlib import Path

from src.vector_store import ChromaStore, SimpleKeywordStore, get_vector_store


RUNTIME_TMP = Path(__file__).parent / "_runtime_tmp"


def _runtime_path(name: str) -> Path:
    RUNTIME_TMP.mkdir(parents=True, exist_ok=True)
    stem = Path(name).stem
    suffix = Path(name).suffix
    return RUNTIME_TMP / f"{stem}_{uuid.uuid4().hex}{suffix}"


def _write_cards(path):
    cards = [
        {
            "case_id": "case-1",
            "scenario": "台风导致港口停运，库存仅支撑36小时",
            "trigger_conditions": ["库存可支撑时间 < 48小时"],
            "failed_reason": "全量空运忽略成本。",
            "improvement_strategy": "采用客户分级保障。",
            "recommended_pattern": "备用供应商 + 关键订单空运 + 非关键订单延期",
            "tags": ["台风", "港口停运", "库存不足"],
        },
        {
            "case_id": "case-2",
            "scenario": "供应商质量异常",
            "trigger_conditions": ["质量抽检失败"],
            "failed_reason": "缺少替代料验证。",
            "improvement_strategy": "提前维护替代料清单。",
            "recommended_pattern": "替代料验证 + 供应商整改",
            "tags": ["质量", "替代料"],
        },
    ]
    path.write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")
    return cards


def test_simple_keyword_store_searches_cards():
    path = _runtime_path("vector_search.json")
    _write_cards(path)
    store = SimpleKeywordStore(path)

    matches = store.search("港口停运")

    assert len(matches) == 1
    assert matches[0]["case_id"] == "case-1"


def test_simple_keyword_store_empty_query_returns_all():
    path = _runtime_path("vector_empty_query.json")
    cards = _write_cards(path)
    store = SimpleKeywordStore(path)

    assert store.search("") == cards


def test_get_vector_store_defaults_to_simple():
    path = _runtime_path("vector_missing_simple.json")
    store = get_vector_store(path=path)

    assert isinstance(store, SimpleKeywordStore)


def test_chroma_store_falls_back_to_simple():
    path = _runtime_path("vector_chroma.json")
    _write_cards(path)
    store = ChromaStore(path)

    matches = store.search("客户分级")

    assert "回退到 SimpleKeywordStore" in store.status_message or "MVP仍回退到 SimpleKeywordStore" in store.status_message
    assert len(matches) == 1


def test_get_vector_store_chroma_does_not_crash():
    path = _runtime_path("vector_missing_chroma.json")
    store = get_vector_store(mode="chroma", path=path)

    assert isinstance(store, ChromaStore)
    assert store.search("anything") == []
