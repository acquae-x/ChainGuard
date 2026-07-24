import json
from pathlib import Path

from src.retrieval_eval import evaluate_store, load_eval_items


ROOT = Path(__file__).resolve().parents[1]


class FixedStore:
    def search(self, query):
        return [{"case_id": "hit"}] if query == "good" else [{"case_id": "miss"}]


def test_expanded_eval_set_has_valid_labels_in_corpus():
    items = load_eval_items(ROOT / "data" / "retrieval_eval.json")
    cards = json.loads((ROOT / "data" / "experience_cards.json").read_text(encoding="utf-8"))
    card_ids = {card["case_id"] for card in cards}

    assert len(items) >= 30
    assert all(set(item["relevant_case_ids"]).issubset(card_ids) for item in items)


def test_evaluate_store_reports_macro_recall_at_k():
    result = evaluate_store(
        FixedStore(),
        [
            {"query": "good", "relevant_case_ids": ["hit"]},
            {"query": "bad", "relevant_case_ids": ["hit"]},
        ],
    )

    assert result["query_count"] == 2
    assert result["recall_at_k"] == {"1": 0.5, "3": 0.5}
