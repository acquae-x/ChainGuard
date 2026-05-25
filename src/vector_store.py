import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def resolve_project_path(path: str | Path) -> Path:
    target = Path(path)
    if target.is_absolute():
        return target
    return PROJECT_ROOT / target


class SimpleKeywordStore:
    def __init__(self, path: str | Path = "data/experience_cards.json") -> None:
        self.path = resolve_project_path(path)

    def load_cards(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"经验卡片 JSON 格式错误：{self.path}，{error}") from error
        if not isinstance(data, list):
            raise ValueError(f"经验卡片文件必须是列表：{self.path}")
        return data

    def search(self, query: str) -> list[dict[str, Any]]:
        cards = self.load_cards()
        normalized_query = query.strip().lower()
        if not normalized_query:
            return cards

        query_terms = [term for term in normalized_query.split() if term] or [normalized_query]
        matches: list[dict[str, Any]] = []

        for card in cards:
            searchable_text = self._card_text(card)
            if normalized_query in searchable_text or any(term in searchable_text for term in query_terms):
                matches.append(card)

        return matches

    @staticmethod
    def _card_text(card: dict[str, Any]) -> str:
        return " ".join(
            [
                str(card.get("scenario", "")),
                str(card.get("failed_reason", "")),
                str(card.get("improvement_strategy", "")),
                str(card.get("recommended_pattern", "")),
                " ".join(str(item) for item in card.get("trigger_conditions", [])),
                " ".join(str(item) for item in card.get("tags", [])),
            ]
        ).lower()


class ChromaStore:
    def __init__(self, path: str | Path = "data/experience_cards.json") -> None:
        self.path = resolve_project_path(path)
        self.fallback = SimpleKeywordStore(self.path)
        try:
            import chromadb  # type: ignore
        except ImportError:
            self.chromadb = None
            self.status_message = "当前未安装 chromadb，已回退到 SimpleKeywordStore。"
        else:
            self.chromadb = chromadb
            self.status_message = "ChromaStore 当前为可选预留实现，MVP仍回退到 SimpleKeywordStore。"

    def search(self, query: str) -> list[dict[str, Any]]:
        return self.fallback.search(query)


def get_vector_store(mode: str = "simple", path: str | Path = "data/experience_cards.json"):
    normalized_mode = (mode or "simple").strip().lower()
    if normalized_mode == "chroma":
        return ChromaStore(path)
    return SimpleKeywordStore(path)
