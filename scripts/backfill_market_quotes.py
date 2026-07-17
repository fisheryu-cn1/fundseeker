#!/usr/bin/env python3
"""Backfill missing MarketQuote rows for configured indices and commodities.

Runs the MarketQuoteCollector against a wide date range so a single invocation
picks up every gap the daily cron missed. Idempotent: ``on_conflict_do_nothing``
on (quote_date, symbol_code) means re-running won't duplicate rows.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from sqlalchemy import desc, func, select
from sqlalchemy.dialects.postgresql import insert

from fundseeker.collectors.market_quote import MarketQuoteCollector
from fundseeker.config import load_config
from fundseeker.models.database import get_engine, get_session_maker
from fundseeker.models.tables import CollectionLog, MarketQuote


def parse_args() -> tuple[date, date]:
    """Parse --start / --end from CLI, defaulting to 2026-06-30 .. today."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2026-06-30",
                        help="YYYY-MM-DD (default 2026-06-30)")
    parser.add_argument("--end", default=date.today().isoformat(),
                        help=f"YYYY-MM-DD (default {date.today().isoformat()})")
    args = parser.parse_args()
    return (
        datetime.strptime(args.start, "%Y-%m-%d").date(),
        datetime.strptime(args.end, "%Y-%m-%d").date(),
    )


def main() -> None:
    start_date, end_date = parse_args()
    if end_date < start_date:
        raise SystemExit(f"--end ({end_date}) must be >= --start ({start_date})")

    config = load_config()
    collector = MarketQuoteCollector(config)
    expected_symbols = {s["symbol_code"] for s in collector.all_symbols}
    print(f"Configured symbols ({len(expected_symbols)}): "
          f"{sorted(expected_symbols)}")

    # 1. Snapshot current coverage per symbol inside the backfill window.
    engine = get_engine()
    Session = get_session_maker(engine)
    with Session() as s:
        rows = s.execute(
            select(MarketQuote.symbol_code,
                   func.count(MarketQuote.id).label("c"),
                   func.min(MarketQuote.quote_date),
                   func.max(MarketQuote.quote_date))
            .where(
                MarketQuote.quote_date >= start_date,
                MarketQuote.quote_date <= end_date,
                MarketQuote.symbol_code.in_(expected_symbols),
            )
            .group_by(MarketQuote.symbol_code)
            .order_by(MarketQuote.symbol_code)
        ).all()
    print(f"\nCoverage in window [{start_date} .. {end_date}] BEFORE backfill:")
    for code, c, mn, mx in rows:
        print(f"  {code:12s}: {c:3d} records, {mn} ~ {mx}")

    # 2. Collect from Eastmoney per index (covers historical range).
    print(f"\nFetching klines for [{start_date} .. {end_date}] ...")
    collected: list[dict] = []
    for cfg in collector.all_symbols:
        if cfg.get("asset_class") == "commodity":
            # Sina only exposes the current trading day for commodities.
            # Skip historical backfill — will be picked up by the daily cron.
            continue
        secid = cfg["secid"]
        try:
            klines = collector._fetch_eastmoney_klines(secid, start_date, end_date)
        except Exception as exc:
            print(f"  {cfg['symbol_code']}: ERROR {exc}")
            continue
        if not klines:
            print(f"  {cfg['symbol_code']}: no klines returned")
            continue
        inserted_count = 0
        for kline in klines:
            date_prefix = kline.split(",", 1)[0]
            try:
                row_date = datetime.strptime(date_prefix, "%Y-%m-%d").date()
            except ValueError:
                continue
            if row_date < start_date or row_date > end_date:
                continue
            from fundseeker.collectors.market_quote import _parse_eastmoney_kline
            parsed = _parse_eastmoney_kline(kline)
            collected.append(
                {
                    "quote_date": parsed["quote_date"],
                    "symbol_code": cfg["symbol_code"],
                    "symbol_name": cfg["symbol_name"],
                    "market_region": cfg["market_region"],
                    "asset_class": cfg["asset_class"],
                    "open_price": parsed["open_price"],
                    "high_price": parsed["high_price"],
                    "low_price": parsed["low_price"],
                    "close_price": parsed["close_price"],
                    "prev_close": parsed["prev_close"],
                    "change_amount": parsed["change_amount"],
                    "change_pct": parsed["change_pct"],
                    "volume": parsed["volume"],
                    "volume_unit": cfg["volume_unit"],
                    "amount": parsed["amount"],
                    "currency": cfg["currency"],
                    "data_source": "https://push2his.eastmoney.com/api/qt/stock/kline/get",
                    "source_code": cfg["secid"],
                }
            )
            inserted_count += 1
        print(f"  {cfg['symbol_code']}: fetched {inserted_count} klines")

    # 3. Insert with on_conflict_do_nothing (idempotent).
    Session = get_session_maker(engine)
    inserted = 0
    skipped = 0
    with Session() as s:
        log = CollectionLog(
            job_name="market_quote_backfill",
            institution_code=None,
            start_time=datetime.utcnow(),
            status="running",
        )
        s.add(log)
        s.commit()

        for q in collected:
            stmt = (
                insert(MarketQuote)
                .values(**q)
                .on_conflict_do_nothing(
                    index_elements=["quote_date", "symbol_code"]
                )
            )
            result = s.execute(stmt)
            if result.rowcount:
                inserted += 1
            else:
                skipped += 1
        s.commit()

        log.end_time = datetime.utcnow()
        log.status = "success"
        log.records_count = inserted
        s.commit()
        log_id = log.id

    print(f"\nInserted {inserted} rows, skipped {skipped} duplicates")
    print(f"Log id: {log_id}")

    # 4. Re-snapshot coverage.
    Session = get_session_maker(engine)
    with Session() as s:
        rows = s.execute(
            select(MarketQuote.symbol_code,
                   func.count(MarketQuote.id).label("c"),
                   func.min(MarketQuote.quote_date),
                   func.max(MarketQuote.quote_date))
            .where(
                MarketQuote.quote_date >= start_date,
                MarketQuote.quote_date <= end_date,
                MarketQuote.symbol_code.in_(expected_symbols),
            )
            .group_by(MarketQuote.symbol_code)
            .order_by(MarketQuote.symbol_code)
        ).all()
    print(f"\nCoverage in window [{start_date} .. {end_date}] AFTER backfill:")
    for code, c, mn, mx in rows:
        print(f"  {code:12s}: {c:3d} records, {mn} ~ {mx}")


if __name__ == "__main__":
    main()