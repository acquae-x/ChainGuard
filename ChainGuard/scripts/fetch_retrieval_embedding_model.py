"""Fetch and verify the exact optional model used by ``EmbeddingStore``."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "paraphrase-multilingual-MiniLM-L12-v2"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=PROJECT_ROOT / ".workspace" / "retrieval-eval" / "hf-cache",
    )
    args = parser.parse_args()
    cache_dir = args.cache_dir.resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    # EmbeddingStore uses local_files_only=True.  Pass this same directory to
    # evaluate_retrieval.py --embedding-cache for an offline-repeatable run.
    os.environ["HF_HOME"] = str(cache_dir)

    from sentence_transformers import SentenceTransformer

    SentenceTransformer(MODEL_ID, cache_folder=str(cache_dir), local_files_only=False)
    # Verify the model can be opened in exactly the offline mode used in product.
    SentenceTransformer(MODEL_ID, cache_folder=str(cache_dir), local_files_only=True)
    print(f"model={MODEL_ID} cache_dir={cache_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
