#!/usr/bin/env python3
"""Add composite index on market_quote for /market page performance.

Background
----------
The market dashboard previously exhibited a 28s cold load: it pulled every
``asset_class = 'stock'`` row along with the macro indices/commodities, then
issued N+1 queries for each symbol's 30-day history. Fix #1 (asset_class
filter) and fix #2 (batch history query) cut the row counts, but for the batch
query to remain fast as the table grows we still need an index that covers:

    WHERE asset_class IN (...) AND symbol_code IN (...)
      AND quote_date <= :end_date
    ORDER BY symbol_code, quote_date DESC

This migration creates the composite index ``(asset_class, quote_date,
symbol_code)`` to support that query path. ``quote_date`` is intentionally
listed before ``symbol_code`` so PostgreSQL can also use it for range scans
and the ``MAX(quote_date)`` grouping in ``list_market_quotes``.

Safe to run repeatedly: ``CREATE INDEX IF NOT EXISTS`` is a no-op when the
index already exists.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import text

from fundseeker.models.database import get_engine


MIGRATION_SQL = """
CREATE INDEX IF NOT EXISTS ix_market_quote_asset_class_date_symbol
    ON market_quote (asset_class, quote_date, symbol_code);
"""


def migrate() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(MIGRATION_SQL))
    print("market_quote composite index migration completed.")


if __name__ == "__main__":
    migrate()