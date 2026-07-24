"""Deterministic, dependency-free retrieval evaluation helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Protocol


class SearchStore(Protocol):
    def search(self, query: str) -> list[dict[str, Any]]: ...


def load_eval_items(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("retrieval evaluation data must be a non-empty list")
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get("query"), str):
            raise ValueError("each evaluation item requires a string query")
        labels = item.get("relevant_case_ids")
        if not isinstance(labels, list) or not labels or not all(isinstance(label, str) for label in labels):
            raise ValueError("each evaluation item requires relevant_case_ids")
    return data


def corpus_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evaluate_store(store: SearchStore, items: list[dict[str, Any]], *, k_values: tuple[int, ...] = (1, 3)) -> dict[str, Any]:
    if not k_values or any(k <= 0 for k in k_values):
        raise ValueError("k_values must contain positive integers")

    hits = {k: 0 for k in k_values}
    rows: list[dict[str, Any]] = []
    for item in items:
        expected = set(item["relevant_case_ids"])
        returned_ids = [result.get("case_id") for result in store.search(item["query"])]
        row = {"query": item["query"], "expected_case_ids": sorted(expected), "top_case_ids": returned_ids[: max(k_values)]}
        for k in k_values:
            hit = bool(expected.intersection(returned_ids[:k]))
            hits[k] += int(hit)
            row[f"hit_at_{k}"] = hit
        rows.append(row)

    count = len(items)
    return {
        "query_count": count,
        "recall_at_k": {str(k): hits[k] / count for k in k_values},
        "rows": rows,
    }
