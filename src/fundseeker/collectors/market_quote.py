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

# Sina real-time quote endpoint (indices + futures).
_SINA_HQ_URL = "https://hq.sinajs.cn/list"

# Maximum number of Sina symbols per HTTP request.
_SINA_BATCH_SIZE = 50

INDEX_SYMBOLS = [
    {
        "symbol_code": "SH000001",
        "symbol_name": "上证指数",
        "market_region": "domestic",
        "asset_class": "index",
        "secid": "1.000001",
        "sina_symbol": "sh000001",
        "currency": "CNY",
        "volume_unit": "lot",
    },
    {
        "symbol_code": "SZ399001",
        "symbol_name": "深证成指",
        "market_region": "domestic",
        "asset_class": "index",
        "secid": "0.399001",
        "sina_symbol": "sz399001",
        "currency": "CNY",
        "volume_unit": "lot",
    },
    {
        "symbol_code": "SZ399006",
        "symbol_name": "创业板指",
        "market_region": "domestic",
        "asset_class": "index",
        "secid": "0.399006",
        "sina_symbol": "sz399006",
        "currency": "CNY",
        "volume_unit": "lot",
    },
    {
        "symbol_code": "SH000300",
        "symbol_name": "沪深300",
        "market_region": "domestic",
        "asset_class": "index",
        "secid": "1.000300",
        "sina_symbol": "sh000300",
        "currency": "CNY",
        "volume_unit": "lot",
    },
    {
        "symbol_code": "SH000016",
        "symbol_name": "上证50",
        "market_region": "domestic",
        "asset_class": "index",
        "secid": "1.000016",
        "sina_symbol": "sh000016",
        "currency": "CNY",
        "volume_unit": "lot",
    },
    {
        "symbol_code": "SH000905",
        "symbol_name": "中证500",
        "market_region": "domestic",
        "asset_class": "index",
        "secid": "1.000905",
        "sina_symbol": "sh000905",
        "currency": "CNY",
        "volume_unit": "lot",
    },
    {
        "symbol_code": "SH000852",
        "symbol_name": "中证1000",
        "market_region": "domestic",
        "asset_class": "index",
        "secid": "1.000852",
        "sina_symbol": "sh000852",
        "currency": "CNY",
        "volume_unit": "lot",
    },
    {
        "symbol_code": "HSI",
        "symbol_name": "恒生指数",
        "market_region": "hk",
        "asset_class": "index",
        "secid": "100.HSI",
        "sina_symbol": "rt_hkHSI",
        "currency": "HKD",
        "volume_unit": "share",
    },
    {
        "symbol_code": "HSCEI",
        "symbol_name": "恒生中国企业指数",
        "market_region": "hk",
        "asset_class": "index",
        "secid": "100.HSCEI",
        "sina_symbol": "rt_hkHSCEI",
        "currency": "HKD",
        "volume_unit": "share",
    },
    {
        "symbol_code": "DJIA",
        "symbol_name": "道琼斯工业指数",
        "market_region": "us",
        "asset_class": "index",
        "secid": "100.DJIA",
        "sina_symbol": "gb_dji",
        "currency": "USD",
        "volume_unit": "share",
    },
    {
        "symbol_code": "NDX",
        "symbol_name": "纳斯达克指数",
        "market_region": "us",
        "asset_class": "index",
        "secid": "100.NDX",
        "sina_symbol": "gb_ixic",
        "currency": "USD",
        "volume_unit": "share",
    },
    {
        "symbol_code": "SPX",
        "symbol_name": "标普500指数",
        "market_region": "us",
        "asset_class": "index",
        "secid": "100.SPX",
        "sina_symbol": "gb_inx",
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
        "sina_symbol": "hf_CL",
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


def _to_int(value: str | None) -> int | None:
    """Convert a string to int, returning None on empty/invalid input."""
    dec = _to_decimal(value)
    if dec is None:
        return None
    try:
        return int(dec)
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


def _find_sina_date_index(parts: list[str]) -> int | None:
    """Locate the standalone date token in a Sina quote CSV."""
    for idx, part in enumerate(parts):
        if re.fullmatch(r"\d{4}[-/]\d{2}[-/]\d{2}", part.strip()):
            return idx
    return None


def _parse_sina_datetime_token(token: str) -> date | None:
    """Extract a date from a token like '2026-07-27 15:30:36'."""
    token = token.strip()
    match = re.match(r"(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}", token)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y-%m-%d").date()
        except ValueError:
            pass
    return None


def _parse_sina_index_line(
    line: str, symbol_cfg: dict[str, Any]
) -> dict[str, Any] | None:
    """Parse one Sina A-share/HK/US index quote line.

    A-share format (sh/sz prefix):
        name,open,prev_close,current,high,low,bid,ask,volume,amount,...,date,time,...
    HK format (rt_hk prefix):
        code,name,open,prev_close,high,low,current,...,date,time,...
    US index format (gb_ prefix):
        name,current,change_pct,date_time,change_amount,open,high,low,...,volume,...,prev_close,...
    """
    match = re.search(r'"([^"]*)"', line)
    if not match:
        return None
    body = match.group(1)
    if not body:
        return None

    parts = body.split(",")
    if len(parts) < 6:
        return None

    sina_symbol = symbol_cfg["sina_symbol"]

    if sina_symbol.startswith("gb_"):
        # US index: needs at least open/high/low/prev_close positions.
        if len(parts) < 26:
            return None
        quote_date = _parse_sina_datetime_token(parts[3]) or date.today()
        close_price = _to_decimal(parts[1])
        change_pct = _to_decimal(parts[2])
        change_amount = _to_decimal(parts[4])
        open_price = _to_decimal(parts[5])
        high_price = _to_decimal(parts[6])
        low_price = _to_decimal(parts[7])
        volume = _to_int(parts[10])
        prev_close = _to_decimal(parts[25])

        if change_amount is None and change_pct is not None and prev_close:
            change_amount = prev_close * change_pct / Decimal("100")
        if change_pct is None and change_amount is not None and prev_close:
            change_pct = change_amount / prev_close * Decimal("100")

        return {
            "quote_date": quote_date,
            "open_price": open_price,
            "high_price": high_price,
            "low_price": low_price,
            "close_price": close_price,
            "prev_close": prev_close,
            "change_amount": change_amount,
            "change_pct": change_pct,
            "volume": volume,
            "amount": None,
            "source_code": sina_symbol,
            "data_source": f"{_SINA_HQ_URL}={sina_symbol}",
        }

    date_idx = _find_sina_date_index(parts)
    if date_idx is None:
        return None

    date_str = parts[date_idx].strip().replace("/", "-")
    try:
        quote_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        quote_date = date.today()

    if sina_symbol.startswith("rt_hk"):
        # HK: code, name, open, prev_close, high, low, current, ...
        if len(parts) < 7:
            return None
        open_price = _to_decimal(parts[2])
        prev_close = _to_decimal(parts[3])
        high_price = _to_decimal(parts[4])
        low_price = _to_decimal(parts[5])
        close_price = _to_decimal(parts[6])
        volume = None
        amount = None
    else:
        # A-share: name, open, prev_close, current, high, low, bid, ask, volume, amount, ...
        if len(parts) < 10:
            return None
        open_price = _to_decimal(parts[1])
        prev_close = _to_decimal(parts[2])
        close_price = _to_decimal(parts[3])
        high_price = _to_decimal(parts[4])
        low_price = _to_decimal(parts[5])
        volume = _to_int(parts[8])
        amount = _to_decimal(parts[9])

    change_amount = None
    if close_price is not None and prev_close is not None:
        change_amount = close_price - prev_close

    change_pct = None
    if change_amount is not None and prev_close:
        change_pct = (change_amount / prev_close) * Decimal("100")

    return {
        "quote_date": quote_date,
        "open_price": open_price,
        "high_price": high_price,
        "low_price": low_price,
        "close_price": close_price,
        "prev_close": prev_close,
        "change_amount": change_amount,
        "change_pct": change_pct,
        "volume": volume,
        "amount": amount,
        "source_code": sina_symbol,
        "data_source": f"{_SINA_HQ_URL}={sina_symbol}",
    }


def _parse_sina_commodity_line(
    line: str, symbol_cfg: dict[str, Any]
) -> dict[str, Any] | None:
    """Parse one Sina commodity quote line (e.g. var hq_str_hf_CL=...)."""
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
    date_idx = _find_sina_date_index(parts)
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

    date_str = parts[date_idx].strip().replace("/", "-")
    try:
        quote_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        quote_date = date.today()

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


def _parse_sina_quote_line(
    line: str, symbol_cfg: dict[str, Any]
) -> dict[str, Any] | None:
    """Dispatch Sina quote parsing by symbol type."""
    sina_symbol = symbol_cfg.get("sina_symbol", "")
    if sina_symbol.startswith("hf_"):
        return _parse_sina_commodity_line(line, symbol_cfg)
    return _parse_sina_index_line(line, symbol_cfg)


def _quote_dict_from_parsed(
    parsed: dict[str, Any], cfg: dict[str, Any]
) -> dict[str, Any]:
    """Build a database-ready quote dict from parsed Sina/Eastmoney data."""
    return {
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

    def _fetch_sina_quotes(self, sina_symbols: list[str]) -> str:
        """Fetch Sina real-time quotes for given symbols in batches of 50."""
        chunks = [
            sina_symbols[i : i + _SINA_BATCH_SIZE]
            for i in range(0, len(sina_symbols), _SINA_BATCH_SIZE)
        ]
        texts: list[str] = []
        for chunk in chunks:
            url = f"{_SINA_HQ_URL}={','.join(chunk)}"
            response = self.http.get(
                url,
                headers={"Referer": "https://finance.sina.com.cn"},
            )
            # GB18030 is a superset of GBK/GB2312 and handles Sina's
            # occasional legacy characters without raising.
            response.encoding = "GB18030"
            texts.append(response.text)
        return "\n".join(texts)

    def _collect_single_index_eastmoney(
        self, cfg: dict[str, Any], target_date: date | None = None
    ) -> list[dict[str, Any]]:
        """Collect one index from Eastmoney K-line API."""
        if target_date is not None:
            start_date = end_date = target_date
        else:
            # Use a 60-day look-back window so a single missed cron run
            # doesn't leave the index series with a permanent gap.
            end_date = date.today()
            start_date = end_date - timedelta(days=60)

        klines = self._fetch_eastmoney_klines(cfg["secid"], start_date, end_date)
        if not klines:
            return []

        results: list[dict[str, Any]] = []
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
                _quote_dict_from_parsed(
                    {
                        **parsed,
                        "data_source": _EASTMONEY_KLINE_URL,
                        "source_code": cfg["secid"],
                    },
                    cfg,
                )
            )
        return results

    def _collect_from_sina(
        self, cfgs: list[dict[str, Any]], target_date: date | None = None
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        """Collect real-time quotes from Sina for the given symbol configs."""
        sina_symbols = [cfg["sina_symbol"] for cfg in cfgs]
        text = self._fetch_sina_quotes(sina_symbols)
        cfg_by_sina = {cfg["sina_symbol"]: cfg for cfg in cfgs}

        results: list[dict[str, Any]] = []
        status: dict[str, dict[str, Any]] = {}

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            # line looks like: var hq_str_sh000001="...";
            symbol_match = re.match(r"var\s+hq_str_(\w+)\s*=", line)
            if not symbol_match:
                continue
            sina_symbol = symbol_match.group(1)
            cfg = cfg_by_sina.get(sina_symbol)
            if cfg is None:
                continue

            parsed = _parse_sina_quote_line(line, cfg)
            if parsed is None:
                continue
            if target_date is not None and parsed["quote_date"] != target_date:
                # Sina only provides the current trading day; skip if it does
                # not match the requested historical date.
                continue

            results.append(_quote_dict_from_parsed(parsed, cfg))
            status[cfg["symbol_code"]] = {
                "status": "success",
                "source": _SINA_HQ_URL,
                "quote_date_min": parsed["quote_date"].isoformat(),
                "quote_date_max": parsed["quote_date"].isoformat(),
            }

        # Mark symbols that did not return usable data as failed.
        for cfg in cfgs:
            symbol_code = cfg["symbol_code"]
            if symbol_code not in status:
                status[symbol_code] = {
                    "status": "failed",
                    "source": None,
                    "quote_date_min": None,
                    "quote_date_max": None,
                }

        return results, status

    def _collect_indices(
        self, target_date: date | None = None
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        """Collect index quotes from Eastmoney, falling back to Sina realtime.

        Eastmoney is the primary source because it provides historical daily
        bars. When Eastmoney fails (SSL/connection/timeout/empty response),
        the configured ``sina_symbol`` is used to fetch today's real-time quote
        from Sina as a fallback so the cron run never leaves a gap.
        """
        results: list[dict[str, Any]] = []
        status: dict[str, dict[str, Any]] = {}

        # Phase 1: Eastmoney primary.
        eastmoney_failed: list[dict[str, Any]] = []
        for cfg in INDEX_SYMBOLS:
            symbol_code = cfg["symbol_code"]
            try:
                symbol_results = self._collect_single_index_eastmoney(
                    cfg, target_date
                )
                if symbol_results:
                    results.extend(symbol_results)
                    quote_dates = [r["quote_date"] for r in symbol_results]
                    status[symbol_code] = {
                        "status": "success",
                        "source": _EASTMONEY_KLINE_URL,
                        "quote_date_min": min(quote_dates).isoformat(),
                        "quote_date_max": max(quote_dates).isoformat(),
                    }
                else:
                    eastmoney_failed.append(cfg)
                    status[symbol_code] = {
                        "status": "failed",
                        "source": None,
                        "quote_date_min": None,
                        "quote_date_max": None,
                    }
            except Exception:
                eastmoney_failed.append(cfg)
                status[symbol_code] = {
                    "status": "failed",
                    "source": None,
                    "quote_date_min": None,
                    "quote_date_max": None,
                }

        # Phase 2: Sina fallback for symbols that failed on Eastmoney and have
        # a configured sina_symbol.
        sina_retry = [cfg for cfg in eastmoney_failed if cfg.get("sina_symbol")]
        if sina_retry:
            sina_results, sina_status = self._collect_from_sina(
                sina_retry, target_date
            )
            results.extend(sina_results)
            for symbol_code, st in sina_status.items():
                if st["status"] == "success":
                    status[symbol_code] = st

        return results, status

    def _collect_commodities(
        self, target_date: date | None = None
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        """Collect commodity quotes from Sina real-time endpoint."""
        results, status = self._collect_from_sina(COMMODITY_SYMBOLS, target_date)
        return results, status

    def _print_collector_summary(
        self, status: dict[str, dict[str, Any]]
    ) -> None:
        """Print per-symbol collection source and status."""
        print("\n[market_quote] per-symbol collection summary")
        total = len(status)
        success = sum(1 for s in status.values() if s["status"] == "success")
        failed = total - success
        print(f"  total symbols : {total}")
        print(f"  success       : {success}")
        print(f"  failed        : {failed}")

        # Group by source so Eastmoney vs Sina is obvious.
        by_source: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for symbol_code, st in sorted(status.items()):
            source = st.get("source") or "failed"
            by_source.setdefault(source, []).append((symbol_code, st))

        for source, items in by_source.items():
            print(f"\n  source: {source}")
            for symbol_code, st in items:
                date_min = st.get("quote_date_min")
                date_max = st.get("quote_date_max")
                if date_min and date_max:
                    if date_min == date_max:
                        date_info = f"date={date_min}"
                    else:
                        date_info = f"dates={date_min}~{date_max}"
                else:
                    date_info = "no date"
                print(f"    {symbol_code}: {st['status']} ({date_info})")

    def collect(
        self, target_date: date | str | None = None
    ) -> list[dict[str, Any]]:
        """Collect market quotes.

        Args:
            target_date: Optional date (``date`` or ``YYYY-MM-DD`` string).
                If provided, only the specified trading day is collected.
                Indices support historical dates via Eastmoney; commodities
                and Sina fallback only support the current trading day.

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
        status: dict[str, dict[str, Any]] = {}

        index_results, index_status = self._collect_indices(parsed_date)
        results.extend(index_results)
        status.update(index_status)

        commodity_results, commodity_status = self._collect_commodities(parsed_date)
        results.extend(commodity_results)
        status.update(commodity_status)

        self._print_collector_summary(status)
        return results
