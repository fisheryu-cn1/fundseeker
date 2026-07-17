"""Collector for major global financial market quotes.

Data sources:
- Domestic / HK / US equity indices: Eastmoney daily K-line API
  (supports historical dates and returns OHLC + volume).
- Commodities (Brent crude, NY gold): Sina Finance real-time futures quote
  (current trading day only, returns latest price, open, high, low,
  previous settlement and quote date).

The collector is designed to be called at most once per day. Duplicate
avoidance is handled by the runner via the ``quote_date`` + ``symbol_code``
unique constraint on ``market_quote``.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import requests

from fundseeker.utils.http import PoliteHttpClient


# Eastmoney K-line endpoint returns daily bars for indices.
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

# Sina international futures / commodity quote endpoint.
_SINA_HQ_URL = "https://hq.sinajs.cn/list"

INDEX_SYMBOLS = [
    {
        "symbol_code": "SH000001",
        "symbol_name": "上证指数",
        "market_region": "domestic",
        "asset_class": "index",
        "secid": "1.000001",
        "currency": "CNY",
        "volume_unit": "lot",
    },
    {
        "symbol_code": "SZ399001",
        "symbol_name": "深证成指",
        "market_region": "domestic",
        "asset_class": "index",
        "secid": "0.399001",
        "currency": "CNY",
        "volume_unit": "lot",
    },
    {
        "symbol_code": "SZ399006",
        "symbol_name": "创业板指",
        "market_region": "domestic",
        "asset_class": "index",
        "secid": "0.399006",
        "currency": "CNY",
        "volume_unit": "lot",
    },
    {
        "symbol_code": "SH000300",
        "symbol_name": "沪深300",
        "market_region": "domestic",
        "asset_class": "index",
        "secid": "1.000300",
        "currency": "CNY",
        "volume_unit": "lot",
    },
    {
        "symbol_code": "SH000016",
        "symbol_name": "上证50",
        "market_region": "domestic",
        "asset_class": "index",
        "secid": "1.000016",
        "currency": "CNY",
        "volume_unit": "lot",
    },
    {
        "symbol_code": "SH000905",
        "symbol_name": "中证500",
        "market_region": "domestic",
        "asset_class": "index",
        "secid": "1.000905",
        "currency": "CNY",
        "volume_unit": "lot",
    },
    {
        "symbol_code": "SH000852",
        "symbol_name": "中证1000",
        "market_region": "domestic",
        "asset_class": "index",
        "secid": "1.000852",
        "currency": "CNY",
        "volume_unit": "lot",
    },
    {
        "symbol_code": "HSI",
        "symbol_name": "恒生指数",
        "market_region": "hk",
        "asset_class": "index",
        "secid": "100.HSI",
        "currency": "HKD",
        "volume_unit": "share",
    },
    {
        "symbol_code": "HSCEI",
        "symbol_name": "恒生中国企业指数",
        "market_region": "hk",
        "asset_class": "index",
        "secid": "100.HSCEI",
        "currency": "HKD",
        "volume_unit": "share",
    },
    {
        "symbol_code": "DJIA",
        "symbol_name": "道琼斯工业指数",
        "market_region": "us",
        "asset_class": "index",
        "secid": "100.DJIA",
        "currency": "USD",
        "volume_unit": "share",
    },
    {
        "symbol_code": "NDX",
        "symbol_name": "纳斯达克指数",
        "market_region": "us",
        "asset_class": "index",
        "secid": "100.NDX",
        "currency": "USD",
        "volume_unit": "share",
    },
    {
        "symbol_code": "SPX",
        "symbol_name": "标普500指数",
        "market_region": "us",
        "asset_class": "index",
        "secid": "100.SPX",
        "currency": "USD",
        "volume_unit": "share",
    },
]

COMMODITY_SYMBOLS = [
    {
        "symbol_code": "BRENT_OIL",
        "symbol_name": "布伦特原油",
        "market_region": "commodity",
        "asset_class": "commodity",
        "sina_symbol": "hf_OIL",
        "currency": "USD",
        "volume_unit": "contract",
    },
    {
        "symbol_code": "GOLD",
        "symbol_name": "纽约黄金",
        "market_region": "commodity",
        "asset_class": "commodity",
        "sina_symbol": "hf_GC",
        "currency": "USD",
        "volume_unit": "contract",
    },
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
    except InvalidOperation:
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


def _parse_sina_commodity_line(
    line: str, symbol_cfg: dict[str, Any]
) -> dict[str, Any] | None:
    """Parse one Sina commodity quote line (e.g. var hq_str_hf_OIL=...)."""
    match = re.search(r'"([^"]*)"', line)
    if not match:
        return None
    body = match.group(1)
    if not body:
        return None

    parts = body.split(",")
    if len(parts) < 14:
        return None

    # Format observed for Sina hf_* symbols:
    # 0 latest/close, 1 change_pct, 2 bid, 3 ask, 4 high, 5 low,
    # 6 quote_time, 7 prev_settlement, 8 open, ...,
    # N-2 date (YYYY-MM-DD), N-1 name
    # Some fields in the middle vary, so we locate the date field explicitly.
    date_idx = None
    for idx, part in enumerate(parts):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", part.strip()):
            date_idx = idx
            break
    if date_idx is None:
        return None

    close_price = _to_decimal(parts[0])
    raw_change_pct = _to_decimal(parts[1])
    high_price = _to_decimal(parts[4])
    low_price = _to_decimal(parts[5])
    prev_close = _to_decimal(parts[7])
    open_price = _to_decimal(parts[8])

    change_amount = None
    if close_price is not None and prev_close is not None:
        change_amount = close_price - prev_close

    change_pct = raw_change_pct
    if change_pct is None and change_amount is not None and prev_close:
        change_pct = (change_amount / prev_close) * Decimal("100")

    quote_date = datetime.strptime(parts[date_idx].strip(), "%Y-%m-%d").date()

    return {
        "quote_date": quote_date,
        "open_price": open_price,
        "high_price": high_price,
        "low_price": low_price,
        "close_price": close_price,
        "prev_close": prev_close,
        "change_amount": change_amount,
        "change_pct": change_pct,
        "volume": None,
        "amount": None,
        "source_code": symbol_cfg["sina_symbol"],
        "data_source": f"{_SINA_HQ_URL}={symbol_cfg['sina_symbol']}",
    }


class MarketQuoteCollector:
    """Collect daily market quotes for configured indices and commodities."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        # Use a short delay for public quote endpoints; they are queried
        # infrequently but we still want to be polite.
        self.http = PoliteHttpClient(
            user_agent=self.config.get("global", {}).get("user_agent"),
            min_delay=self.config.get("request", {}).get("min_delay_seconds", 0.5),
            max_delay=self.config.get("request", {}).get("max_delay_seconds", 1.5),
            max_retries=self.config.get("request", {}).get("max_retries", 3),
            timeout=self.config.get("request", {}).get("timeout", 30),
            respect_robots_txt=False,
        )

    @property
    def all_symbols(self) -> list[dict[str, Any]]:
        """Return the full list of configured market symbols."""
        return INDEX_SYMBOLS + COMMODITY_SYMBOLS

    def _fetch_eastmoney_klines(
        self, secid: str, start_date: date, end_date: date
    ) -> list[str]:
        """Fetch daily K-line strings from Eastmoney for a given secid."""
        params = {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12",
            "fields2": ",".join([f"f{51 + i}" for i in range(len(_EASTMONEY_KLINE_FIELDS))]),
            "klt": "101",
            "fqt": "0",
            "beg": start_date.strftime("%Y%m%d"),
            "end": end_date.strftime("%Y%m%d"),
        }
        response = self.http.get(_EASTMONEY_KLINE_URL, params=params)
        payload = response.json()
        data = payload.get("data") or {}
        return data.get("klines", [])

    def _fetch_sina_commodities(self) -> str:
        """Fetch Sina real-time quotes for all configured commodities."""
        symbols = ",".join(s["sina_symbol"] for s in COMMODITY_SYMBOLS)
        url = f"{_SINA_HQ_URL}={symbols}"
        response = self.http.get(url, headers={"Referer": "https://finance.sina.com.cn"})
        # Sina returns GB2312 encoded JavaScript text.
        response.encoding = "gb2312"
        return response.text

    def _collect_indices(
        self, target_date: date | None = None
    ) -> list[dict[str, Any]]:
        """Collect index quotes from Eastmoney.

        Each Eastmoney kline request returns the full requested window. We
        iterate over every kline in that window and emit one quote per trading
        day, so a single cron run naturally backfills any gap left by previous
        missed runs. When ``target_date`` is given, only that exact date is
        emitted (single-day mode).
        """
        results: list[dict[str, Any]] = []
        for cfg in INDEX_SYMBOLS:
            if target_date is not None:
                start_date = end_date = target_date
            else:
                # Use a 60-day look-back window so a single missed cron run
                # doesn't leave the index series with a permanent gap.
                end_date = date.today()
                start_date = end_date - timedelta(days=60)

            klines = self._fetch_eastmoney_klines(cfg["secid"], start_date, end_date)
            if not klines:
                continue

            for kline in klines:
                # Skip rows whose date prefix lies outside the requested
                # window (Eastmoney sometimes returns a few adjacent days).
                date_prefix = kline.split(",", 1)[0]
                try:
                    row_date = datetime.strptime(date_prefix, "%Y-%m-%d").date()
                except ValueError:
                    continue
                if target_date is not None and row_date != target_date:
                    continue
                if row_date < start_date or row_date > end_date:
                    continue

                parsed = _parse_eastmoney_kline(kline)
                results.append(
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
                        "data_source": _EASTMONEY_KLINE_URL,
                        "source_code": cfg["secid"],
                    }
                )
        return results

    def _collect_commodities(
        self, target_date: date | None = None
    ) -> list[dict[str, Any]]:
        """Collect commodity quotes from Sina real-time endpoint."""
        text = self._fetch_sina_commodities()
        cfg_by_symbol = {s["sina_symbol"]: s for s in COMMODITY_SYMBOLS}
        results: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            # line looks like: var hq_str_hf_OIL="...";
            symbol_match = re.match(r"var\s+hq_str_(\w+)\s*=", line)
            if not symbol_match:
                continue
            sina_symbol = symbol_match.group(1)
            cfg = cfg_by_symbol.get(sina_symbol)
            if cfg is None:
                continue
            parsed = _parse_sina_commodity_line(line, cfg)
            if parsed is None:
                continue
            if target_date is not None and parsed["quote_date"] != target_date:
                # Sina only provides the current trading day; skip if it does
                # not match the requested historical date.
                continue
            results.append(
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
                    "data_source": parsed["data_source"],
                    "source_code": parsed["source_code"],
                }
            )
        return results

    def collect(
        self, target_date: date | str | None = None
    ) -> list[dict[str, Any]]:
        """Collect market quotes.

        Args:
            target_date: Optional date (``date`` or ``YYYY-MM-DD`` string).
                If provided, only the specified trading day is collected.
                Indices support historical dates via Eastmoney; commodities
                only support the current trading day offered by Sina.

        Returns:
            A list of quote dicts ready for database insertion.
        """
        if target_date is None:
            parsed_date: date | None = None
        elif isinstance(target_date, date):
            parsed_date = target_date
        else:
            parsed_date = datetime.strptime(str(target_date), "%Y-%m-%d").date()

        results: list[dict[str, Any]] = []
        results.extend(self._collect_indices(parsed_date))
        results.extend(self._collect_commodities(parsed_date))
        return results
