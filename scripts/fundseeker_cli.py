#!/usr/bin/env python3
"""Unified CLI entry point for FundSeeker data collection.

Designed for scheduled execution by OpenClaw or similar agentic schedulers.
The script runs collection tasks and prints a concise summary report to stdout.

Examples:
    # Initialize database tables
    PYTHONPATH=src python scripts/fundseeker_cli.py init-db

    # Collect everything (products, NAV, holdings)
    PYTHONPATH=src python scripts/fundseeker_cli.py collect --all

    # Collect only fund-company products and NAV
    PYTHONPATH=src python scripts/fundseeker_cli.py collect --funds

    # Collect only bank wealth-management products and NAV
    PYTHONPATH=src python scripts/fundseeker_cli.py collect --bank-wm

    # Collect only holdings for fund products
    PYTHONPATH=src python scripts/fundseeker_cli.py collect --holdings

    # Collect major global market quotes for today
    PYTHONPATH=src python scripts/fundseeker_cli.py collect --market-quotes

    # Collect market quotes for a specific historical date
    PYTHONPATH=src python scripts/fundseeker_cli.py collect --market-quotes --market-date 2026-06-30

    # Only print the current summary report without collecting
    PYTHONPATH=src python scripts/fundseeker_cli.py report

    # Collect a single institution
    PYTHONPATH=src python scripts/fundseeker_cli.py collect --fund GF
    PYTHONPATH=src python scripts/fundseeker_cli.py collect --bank SPD
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from fundseeker.models.database import get_engine
from fundseeker.models.tables import Base
from fundseeker.runner import (
    BANK_WM_COLLECTORS,
    FUND_COLLECTORS,
    TaskResult,
    build_summary,
    print_summary,
    run_bank_wm,
    run_fund_company,
    run_holdings,
    run_market_quotes,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fundseeker_cli",
        description="FundSeeker unified data collection CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init-db
    subparsers.add_parser("init-db", help="Create/reset database tables")

    # collect
    collect_parser = subparsers.add_parser(
        "collect", help="Run one or more collection tasks"
    )
    collect_parser.add_argument(
        "--all",
        action="store_true",
        help="Run all collectors (funds, bank WM, holdings)",
    )
    collect_parser.add_argument(
        "--funds",
        action="store_true",
        help="Run all fund-company collectors",
    )
    collect_parser.add_argument(
        "--bank-wm",
        action="store_true",
        help="Run all bank wealth-management collectors",
    )
    collect_parser.add_argument(
        "--holdings",
        action="store_true",
        help="Run holding collector for all fund companies",
    )
    collect_parser.add_argument(
        "--fund",
        choices=list(FUND_COLLECTORS.keys()),
        help="Run a single fund-company collector",
    )
    collect_parser.add_argument(
        "--bank",
        choices=list(BANK_WM_COLLECTORS.keys()),
        help="Run a single bank wealth-management collector",
    )
    collect_parser.add_argument(
        "--holding-code",
        help="Run holding collector for a single institution code",
    )
    collect_parser.add_argument(
        "--holding-years",
        type=int,
        default=1,
        help="Number of historical years for holdings (default: 1, max 10)",
    )
    collect_parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Re-collect holdings even if a report already exists",
    )
    collect_parser.add_argument(
        "--market-quotes",
        action="store_true",
        help="Collect major global market quotes (indices + commodities)",
    )
    collect_parser.add_argument(
        "--market-date",
        type=str,
        default=None,
        help="Collect market quotes for a specific date (YYYY-MM-DD)",
    )
    collect_parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-collection even if today's product/NAV/market data already exists",
    )

    # report
    subparsers.add_parser(
        "report", help="Print current collection summary without running tasks"
    )

    return parser.parse_args()


def cmd_init_db() -> int:
    engine = get_engine()
    print(f"Creating tables in: {engine.url}")
    Base.metadata.create_all(engine)
    print("All tables created successfully.")
    return 0


def cmd_report() -> int:
    summary = build_summary([])
    print_summary(summary)
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    tasks: list[TaskResult] = []

    check_existing = not args.force

    if args.fund:
        tasks.append(run_fund_company(args.fund, check_existing=check_existing))
    if args.bank:
        tasks.append(run_bank_wm(args.bank, check_existing=check_existing))
    if args.holding_code:
        tasks.append(
            run_holdings(
                institution_code=args.holding_code,
                years=args.holding_years,
                skip_existing=not args.no_skip_existing,
            )
        )

    # Batch modes
    if args.funds or args.all:
        for code in FUND_COLLECTORS.keys():
            tasks.append(run_fund_company(code, check_existing=check_existing))
    if args.bank_wm or args.all:
        for code in BANK_WM_COLLECTORS.keys():
            tasks.append(run_bank_wm(code, check_existing=check_existing))
    if args.market_quotes or args.market_date or args.all:
        tasks.append(
            run_market_quotes(
                target_date=args.market_date,
                check_existing=True,
                force=args.force,
            )
        )

    if args.holdings or args.all:
        tasks.append(
            run_holdings(
                institution_code=None,
                years=args.holding_years,
                skip_existing=not args.no_skip_existing,
            )
        )

    if not tasks:
        print("No collection task selected. Use --help for options.", file=sys.stderr)
        return 2

    summary = build_summary(tasks)
    print_summary(summary)

    failed = [t for t in tasks if t.status == "failed"]
    return 1 if failed else 0


def main() -> int:


    args = parse_args()

    # Clamp user-supplied holding years (P2, review 2026-08-20 fs 分析 §3.1):
    # one product × N years multiplies HTTP requests; without a cap a typo
    # (e.g. --holding-years 1000) can hammer upstream sites.
    if getattr(args, "holding_years", None) is not None:
        args.holding_years = max(1, min(int(args.holding_years), 10))

    if args.command == "init-db":
        return cmd_init_db()
    if args.command == "report":
        return cmd_report()
    if args.command == "collect":
        return cmd_collect(args)

    print(f"Unknown command: {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
