#!/usr/bin/env python3
"""Run a bank wealth-management collector (ZY, JX, ...) and persist results.

This script is kept for backward compatibility. New automation should use
``scripts/fundseeker_cli.py`` instead.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from fundseeker.runner import BANK_WM_COLLECTORS, run_bank_wm


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect bank wealth management product list and NAV."
    )
    parser.add_argument(
        "code",
        choices=list(BANK_WM_COLLECTORS.keys()),
        help="Bank WM institution code",
    )
    args = parser.parse_args()

    result = run_bank_wm(args.code)
    print(
        f"ProductInfo inserted: {result.inserted}, skipped: {result.skipped}; "
        f"records: {result.records_count}"
    )
    if result.status == "failed":
        print(f"Collection failed: {result.error_message}", file=sys.stderr)
        return 1
    print("Collection completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
