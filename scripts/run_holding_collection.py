#!/usr/bin/env python3
"""Collect portfolio holding data for already-persisted products.

This script is kept for backward compatibility. New automation should use
``scripts/fundseeker_cli.py`` instead.

Examples:
    # All fund companies
    PYTHONPATH=src python scripts/run_holding_collection.py

    # Only GF, limit to 10 products
    PYTHONPATH=src python scripts/run_holding_collection.py --code GF --limit 10
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from fundseeker.runner import run_holdings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect portfolio holdings for existing products."
    )
    parser.add_argument(
        "--code",
        help="Institution code to filter products (e.g. GF, ChinaAMC).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of products to process (ignored by runner).",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=1,
        help="Number of historical years to fetch for each product (max 10).",
    )
    parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Re-collect holdings even if a report already exists.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.limit is not None:
        print(
            "WARNING: --limit is not supported by the unified runner; "
            "use fundseeker_cli.py --holding-code for partial runs.",
            file=sys.stderr,
        )

    result = run_holdings(
        institution_code=args.code,
        years=max(1, min(int(args.years), 10)),  # clamp (review 2026-08-20)
        skip_existing=not args.no_skip_existing,
    )
    print(
        f"Holdings: records={result.records_count}, "
        f"skipped_products={result.skipped}, duration={result.duration_seconds:.1f}s"
    )
    if result.status == "failed":
        print(f"Collection failed: {result.error_message}", file=sys.stderr)
        return 1
    print("Holding collection completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
