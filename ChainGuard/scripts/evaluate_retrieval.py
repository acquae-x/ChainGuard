"""Run the fixed retrieval evaluation and write a machine-readable result."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.retrieval_eval import corpus_sha256, evaluate_store, load_eval_items  # noqa: E402
from src.vector_store import EmbeddingStore, TfidfStore  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", choices=("tfidf", "embedding"), required=True)
    parser.add_argument("--cards", type=Path, default=PROJECT_ROOT / "data" / "experience_cards.json")
    parser.add_argument("--eval-data", type=Path, default=PROJECT_ROOT / "data" / "retrieval_eval.json")
    parser.add_argument(
        "--embedding-cache",
        type=Path,
        help="optional local model cache; required only for an offline embedding comparison",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cards_path = args.cards.resolve()
    eval_path = args.eval_data.resolve()
    items = load_eval_items(eval_path)
    store = (
        TfidfStore(cards_path)
        if args.store == "tfidf"
        else EmbeddingStore(cards_path, cache_folder=args.embedding_cache)
    )
    result = evaluate_store(store, items)
    result.update(
        {
            "store": args.store,
            "degraded": bool(getattr(store, "degraded", lambda: False)()),
            "cards_path": str(cards_path),
            "cards_sha256": corpus_sha256(cards_path),
            "eval_path": str(eval_path),
            "eval_sha256": corpus_sha256(eval_path),
            "embedding_cache": str(args.embedding_cache.resolve()) if args.embedding_cache else None,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metrics = result["recall_at_k"]
    print(f"{args.store}: queries={result['query_count']} R@1={metrics['1']:.1%} R@3={metrics['3']:.1%} degraded={result['degraded']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
