from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.webapi.jwt_tokens import create_metrics_token  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a least-privilege JWT for Prometheus /metrics scraping."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Token validity in days (default: 30).",
    )
    parser.add_argument(
        "--subject",
        default="prometheus",
        help="JWT subject used for operational identification.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write only the token to this file instead of standard output.",
    )
    args = parser.parse_args()
    if args.days <= 0:
        parser.error("--days must be greater than zero")

    token = create_metrics_token(
        expires=timedelta(days=args.days),
        subject=args.subject,
    )
    if args.output is None:
        print(token)
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(f"{token}\n", encoding="utf-8")
    print(f"wrote Prometheus metrics token to {args.output}")


if __name__ == "__main__":
    main()
