"""Stock quote fetching and backfill for similarity attribution.

Fetches daily K-lines from Eastmoney (the same source used by
``MarketQuoteCollector``) for the stocks held by clustered products and stores
them in the shared ``market_quote`` table.  This keeps the similarity service's
attribution layer independent of the core collectors while re-using the existing
quote storage.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from fundseeker.models.database import get_engine, get_session_maker
from fundseeker.models.tables import MarketQuote
from fundseeker.utils.http import PoliteHttpClient


_EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_EASTMONEY_KLINE_FIELDS = [
    "date",
    "open",
    "close",
    "high",
    "low",
    "volume",
    "amount",
    "amplitude",
    "change_pct",
    "change_amount",
    "turnover",
]


def _to_decimal(value: str | None) -> Decimal | None:
    """Convert a string to Decimal, returning None on empty/invalid input."""
    if value is None:
        return None
    value = value.strip().replace(",", "")
    if value in ("", "-", "null", "None"):
        return None
    try:
        return Decimal(value)
    except Exception:
        return None


def _parse_eastmoney_kline(kline: str) -> dict[str, Any]:
    """Parse a single Eastmoney K-line CSV string."""
    parts = kline.split(",")
    data: dict[str, Any] = {}
    for idx, field in enumerate(_EASTMONEY_KLINE_FIELDS):
        data[field] = parts[idx] if idx < len(parts) else None

    open_price = _to_decimal(data.get("open"))
    close_price = _to_decimal(data.get("close"))
    high_price = _to_decimal(data.get("high"))
    low_price = _to_decimal(data.get("low"))
    change_amount = _to_decimal(data.get("change_amount"))
    change_pct = _to_decimal(data.get("change_pct"))
    volume = None
    if data.get("volume"):
        try:
            volume = int(Decimal(data["volume"]))
        except Exception:
            volume = None
    amount = _to_decimal(data.get("amount"))

    prev_close = None
    if close_price is not None and change_amount is not None:
        prev_close = close_price - change_amount

    return {
        "quote_date": datetime.strptime(data["date"], "%Y-%m-%d").date(),
        "open_price": open_price,
        "high_price": high_price,
        "low_price": low_price,
        "close_price": close_price,
        "prev_close": prev_close,
        "change_amount": change_amount,
        "change_pct": change_pct,
        "volume": volume,
        "amount": amount,
    }


def _market_to_secid_prefix(market: str) -> str | None:
    """Map internal market code to Eastmoney secid prefix."""
    market = (market or "").upper().strip()
    if market == "SH":
        return "1"
    if market == "SZ":
        return "0"
    if market == "HK":
        return "128"
    if market == "BJ":
        # 北交所在 Eastmoney K-line 接口中尝试使用沪市/深市前缀；
        # 实际数据若不可用则跳过。
        return "1"
    return None


def _market_region(market: str) -> str:
    market = (market or "").upper().strip()
    if market == "HK":
        return "hk"
    return "domestic"


def _symbol_code(code: str, market: str) -> str:
    return f"{market.upper()}{code}"


def fetch_stock_quotes(
    code: str,
    market: str,
    name: str | None,
    start_date: date,
    end_date: date,
    client: PoliteHttpClient | None = None,
) -> list[dict[str, Any]]:
    """Fetch daily quotes for a single stock from Eastmoney.

    Returns:
        A list of quote dicts ready for ``market_quote`` insertion.
    """
    prefix = _market_to_secid_prefix(market)
    if prefix is None:
        return []

    secid = f"{prefix}.{code}"
    if client is None:
        # Use a short delay because we may query many symbols sequentially.
        client = PoliteHttpClient(min_delay=0.1, max_delay=0.3, respect_robots_txt=False)

    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12",
        "fields2": ",".join([f"f{51 + i}" for i in range(len(_EASTMONEY_KLINE_FIELDS))]),
        "klt": "101",
        "fqt": "0",
        "beg": start_date.strftime("%Y%m%d"),
        "end": end_date.strftime("%Y%m%d"),
    }

    response = client.get(_EASTMONEY_KLINE_URL, params=params)
    payload = response.json()
    data = payload.get("data") or {}
    klines = data.get("klines") or []
    symbol_name = data.get("name") or name or f"{market}{code}"

    results: list[dict[str, Any]] = []
    for kline in klines:
        parsed = _parse_eastmoney_kline(kline)
        results.append(
            {
                "quote_date": parsed["quote_date"],
                "symbol_code": _symbol_code(code, market),
                "symbol_name": symbol_name,
                "market_region": _market_region(market),
                "asset_class": "stock",
                "open_price": _decimal_or_none(parsed["open_price"]),
                "high_price": _decimal_or_none(parsed["high_price"]),
                "low_price": _decimal_or_none(parsed["low_price"]),
                "close_price": _decimal_or_none(parsed["close_price"]),
                "prev_close": _decimal_or_none(parsed["prev_close"]),
                "change_amount": _decimal_or_none(parsed["change_amount"]),
                "change_pct": _decimal_or_none(parsed["change_pct"]),
                "volume": parsed["volume"],
                "volume_unit": "share",
                "amount": _decimal_or_none(parsed["amount"]),
                "currency": "HKD" if market.upper() == "HK" else "CNY",
                "data_source": _EASTMONEY_KLINE_URL,
                "source_code": secid,
            }
        )
    return results


def _decimal_or_none(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def load_holding_symbols(report_date: date | str) -> list[tuple[str, str, str | None]]:
    """Return unique (asset_code, market, asset_name) tuples for a report date."""
    if isinstance(report_date, str):
        report_date = date.fromisoformat(report_date)

    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text(
                """
                SELECT DISTINCT asset_code, market, MAX(asset_name) AS asset_name
                FROM product_holding
                WHERE report_date = :report_date
                  AND asset_type = 'stock'
                GROUP BY asset_code, market
                """
            ),
            {"report_date": report_date},
        ).fetchall()
    return [(row.asset_code, row.market, row.asset_name) for row in result]


def refresh_stock_quotes(
    report_date: date | str,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
    symbols: list[tuple[str, str, str | None]] | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Backfill ``market_quote`` for stocks held on ``report_date``.

    Args:
        report_date: The holdings report date used to select symbols.
        start_date: Start of quote window (defaults to report_date).
        end_date: End of quote window (defaults to today).
        symbols: Optional explicit list of (code, market, name) to refresh.
        dry_run: If True, only count without writing to DB.

    Returns:
        Dict with counts: symbols_total, quotes_fetched, quotes_inserted,
        symbols_failed.
    """
    if isinstance(report_date, str):
        report_date = date.fromisoformat(report_date)
    if start_date is None:
        start_date = report_date
    elif isinstance(start_date, str):
        start_date = date.fromisoformat(start_date)
    if end_date is None:
        end_date = date.today()
    elif isinstance(end_date, str):
        end_date = date.fromisoformat(end_date)

    if symbols is None:
        symbols = load_holding_symbols(report_date)

    client = PoliteHttpClient(min_delay=0.1, max_delay=0.3, respect_robots_txt=False)
    all_quotes: list[dict[str, Any]] = []
    failed_symbols: list[tuple[str, str]] = []

    for code, market, name in symbols:
        try:
            quotes = fetch_stock_quotes(code, market, name, start_date, end_date, client=client)
            all_quotes.extend(quotes)
        except Exception:
            failed_symbols.append((code, market))

    stats = {
        "symbols_total": len(symbols),
        "quotes_fetched": len(all_quotes),
        "symbols_failed": len(failed_symbols),
        "quotes_inserted": 0,
    }

    if dry_run or not all_quotes:
        return stats

    Session = get_session_maker()
    with Session() as session:
        for quote in all_quotes:
            stmt = pg_insert(MarketQuote).values(**quote)
            update_dict = {
                c.name: stmt.excluded[c.name]
                for c in MarketQuote.__table__.columns
                if c.name not in ("id", "quote_date", "symbol_code", "created_at")
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=["quote_date", "symbol_code"],
                set_=update_dict,
            )
            session.execute(stmt)
        session.commit()

    stats["quotes_inserted"] = len(all_quotes)
    return stats
