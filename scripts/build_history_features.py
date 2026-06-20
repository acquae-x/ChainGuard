from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.history_pipeline import HistoryPipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build ChainGuard historical decision features.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("--batch-size", type=int, default=100)

    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("--cutoff", required=True)
    snapshot_parser.add_argument("--version", required=True)
    snapshot_parser.add_argument("--train-end", required=True)
    snapshot_parser.add_argument("--val-end", required=True)

    build_cards_parser = subparsers.add_parser("build-cards")
    build_cards_parser.add_argument("--overwrite", action="store_true", default=False)

    train_classifier_parser = subparsers.add_parser("train-classifier")
    train_classifier_parser.add_argument(
        "--train-end",
        default="2026-03-15",
        help="Training split end date, ISO 8601 exclusive.",
    )
    train_classifier_parser.add_argument(
        "--validation-end",
        default="2026-04-01",
        help="Validation split end date, ISO 8601 exclusive.",
    )

    args = parser.parse_args(argv)
    pipeline = HistoryPipeline()

    try:
        if args.command == "train-classifier":
            import csv as _csv

            from src.model_registry import ModelRegistry
            from src.training_dataset import split_by_time, train_prior_classifier

            csv_path = PROJECT_ROOT / "demo_assets/enterprise/csv/historical_decisions.csv"
            try:
                with open(csv_path, encoding="utf-8-sig") as _f:
                    records = list(_csv.DictReader(_f))
            except FileNotFoundError:
                print(f"error: CSV not found: {csv_path}", file=sys.stderr)
                return 1

            split = split_by_time(
                records,
                time_field="created_at",
                train_end=args.train_end,
                validation_end=args.validation_end,
            )
            clf = train_prior_classifier(split.train, label_field="outcome_status")
            metrics = split.evaluate_prior(clf)
            registry = ModelRegistry()
            record = registry.register(snapshot_version="prior-v1", metrics=metrics)
            registry.promote_stable(record.version_id)
            print(
                f"accuracy={metrics['accuracy']:.3f}"
                f"  total_train={len(split.train)}"
                f"  total_test={len(split.test)}"
            )
            return 0
        if args.command == "build-cards":
            import csv as _csv

            from src.learning import build_experience_cards_from_history

            csv_path = PROJECT_ROOT / "demo_assets/enterprise/csv/historical_decisions.csv"
            try:
                with open(csv_path, encoding="utf-8-sig") as _f:
                    records = list(_csv.DictReader(_f))
            except FileNotFoundError:
                print(f"error: CSV not found: {csv_path}", file=sys.stderr)
                return 1
            result = build_experience_cards_from_history(records, overwrite=args.overwrite)
            print(
                f"added={result['added']} skipped={result['skipped']} "
                f"total_after={result['total_after']}"
            )
            return 0
        if args.command == "ingest":
            report = pipeline.ingest_incremental(batch_size=args.batch_size)
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "snapshot":
            snapshot = pipeline.build_training_snapshot(
                cutoff_time=args.cutoff,
                snapshot_version=args.version,
                train_end=args.train_end,
                validation_end=args.val_end,
            )
            print(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2))
            return 0
    except Exception as error:
        print(f"error: {type(error).__name__}: {error}", file=sys.stderr)
        return 1

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
