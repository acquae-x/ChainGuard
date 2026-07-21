import json
import math
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def resolve_project_path(path: str | Path) -> Path:
    target = Path(path)
    if target.is_absolute():
        return target
    return PROJECT_ROOT / target


class SimpleKeywordStore:
    def __init__(self, path: str | Path = "data/experience_cards.json", *, cards: list[dict[str, Any]] | None = None) -> None:
        self.path = resolve_project_path(path)
        # Web tenant retrieval supplies already-authorized cards from the DB.
        # Keeping this as an optional source reuses the exact same ranking code
        # while preventing a global JSON file from participating in tenant runs.
        self.cards = cards

    def load_cards(self) -> list[dict[str, Any]]:
        if self.cards is not None:
            return list(self.cards)
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


class TfidfStore(SimpleKeywordStore):
    def search(self, query: str) -> list[dict[str, Any]]:
        cards = self.load_cards_safely()
        normalized_query = query.strip()
        if not cards or not normalized_query:
            return []

        card_texts = [self._card_text(card) for card in cards]
        try:
            scores = self._sklearn_scores(card_texts, normalized_query)
        except Exception:
            scores = self._local_scores(card_texts, normalized_query)

        ranked = [
            (score, index, card)
            for index, (score, card) in enumerate(zip(scores, cards))
            if score > 0
        ]
        ranked.sort(key=lambda item: (item[0], -item[1]), reverse=True)
        return [card for _, _, card in ranked]

    def degraded(self) -> bool:
        return False

    def load_cards_safely(self) -> list[dict[str, Any]]:
        try:
            return self.load_cards()
        except (json.JSONDecodeError, ValueError, OSError):
            return []

    @staticmethod
    def _sklearn_scores(card_texts: list[str], query: str) -> list[float]:
        from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore
        from sklearn.metrics.pairwise import cosine_similarity  # type: ignore

        vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(1, 3))
        matrix = vectorizer.fit_transform([*card_texts, query.lower()])
        similarities = cosine_similarity(matrix[-1], matrix[:-1])[0]
        return [float(score) for score in similarities]

    @classmethod
    def _local_scores(cls, card_texts: list[str], query: str) -> list[float]:
        documents = [cls._char_wb_ngrams(text) for text in card_texts]
        query_terms = cls._char_wb_ngrams(query.lower())
        if not query_terms:
            return [0.0 for _ in card_texts]

        doc_count = len(documents)
        document_frequency: dict[str, int] = {}
        for terms in documents:
            for term in set(terms):
                document_frequency[term] = document_frequency.get(term, 0) + 1

        query_vector = cls._tfidf_vector(
            query_terms,
            document_frequency,
            doc_count,
        )
        return [
            cls._cosine_similarity(
                query_vector,
                cls._tfidf_vector(terms, document_frequency, doc_count),
            )
            for terms in documents
        ]

    @staticmethod
    def _char_wb_ngrams(text: str) -> list[str]:
        terms: list[str] = []
        for word in text.lower().split():
            padded = f" {word} "
            for size in range(1, 4):
                terms.extend(
                    padded[index : index + size]
                    for index in range(0, len(padded) - size + 1)
                )
        return terms

    @staticmethod
    def _tfidf_vector(
        terms: list[str],
        document_frequency: dict[str, int],
        doc_count: int,
    ) -> dict[str, float]:
        if not terms:
            return {}
        counts: dict[str, int] = {}
        for term in terms:
            counts[term] = counts.get(term, 0) + 1
        total = len(terms)
        vector: dict[str, float] = {}
        for term, count in counts.items():
            idf = math.log((1 + doc_count) / (1 + document_frequency.get(term, 0))) + 1
            vector[term] = (count / total) * idf
        return vector

    @staticmethod
    def _cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
        if not left or not right:
            return 0.0
        numerator = sum(value * right.get(term, 0.0) for term, value in left.items())
        if numerator <= 0:
            return 0.0
        left_norm = math.sqrt(sum(value * value for value in left.values()))
        right_norm = math.sqrt(sum(value * value for value in right.values()))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return numerator / (left_norm * right_norm)


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


class EmbeddingStore:
    def __init__(self, path: str | Path = "data/experience_cards.json") -> None:
        self.path = resolve_project_path(path)
        self.fallback = TfidfStore(self.path)
        self._available = False
        self._model = None
        try:
            import importlib

            module = importlib.import_module("sentence_transformers")
            model_class = getattr(module, "SentenceTransformer")
            self._model = model_class(
                "paraphrase-multilingual-MiniLM-L12-v2",
                local_files_only=True,
            )
        except Exception:
            self._model = None
        else:
            self._available = True

    def search(self, query: str) -> list[dict[str, Any]]:
        if not self._available or self._model is None:
            return self.fallback.search(query)

        cards = self.fallback.load_cards_safely()
        normalized_query = query.strip()
        if not cards or not normalized_query:
            return []

        card_texts = [SimpleKeywordStore._card_text(card) for card in cards]
        try:
            embeddings = self._model.encode([normalized_query.lower(), *card_texts])
            query_vector = list(embeddings[0])
            card_vectors = [list(vector) for vector in embeddings[1:]]
            scores = [
                self._dense_cosine_similarity(query_vector, card_vector)
                for card_vector in card_vectors
            ]
        except Exception:
            return self.fallback.search(query)

        ranked = [
            (score, index, card)
            for index, (score, card) in enumerate(zip(scores, cards))
            if score > 0
        ]
        ranked.sort(key=lambda item: (item[0], -item[1]), reverse=True)
        return [card for _, _, card in ranked]

    def degraded(self) -> bool:
        return not self._available

    @staticmethod
    def _dense_cosine_similarity(left: list[float], right: list[float]) -> float:
        if not left or not right:
            return 0.0
        numerator = sum(a * b for a, b in zip(left, right))
        if numerator <= 0:
            return 0.0
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return numerator / (left_norm * right_norm)


def get_vector_store(
    mode: str = "tfidf",
    path: str | Path = "data/experience_cards.json",
    *,
    cards: list[dict[str, Any]] | None = None,
):
    normalized_mode = (mode or "tfidf").strip().lower()
    if normalized_mode == "chroma":
        return ChromaStore(path) if cards is None else TfidfStore(path, cards=cards)
    if normalized_mode == "embedding":
        return EmbeddingStore(path) if cards is None else TfidfStore(path, cards=cards)
    if normalized_mode in {"keyword", "simple"}:
        return SimpleKeywordStore(path, cards=cards)
    if normalized_mode == "tfidf":
        return TfidfStore(path, cards=cards)
    return TfidfStore(path, cards=cards)
