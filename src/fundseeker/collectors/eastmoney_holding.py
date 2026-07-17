"""Eastmoney (Tiantian Fund) portfolio holding collector.

Collects quarterly top-10 stock holdings, industry allocation, bond holdings,
and asset allocation for public funds. This collector works for any fund whose
code is known (regardless of fund company), making it reusable across all
fund-company products already collected in the database.
"""

from __future__ import annotations

import re
from datetime import date
from html import unescape
from typing import Any

from fundseeker.collectors.holding_base import HoldingCollector


class EastmoneyFundHoldingCollector(HoldingCollector):
    """Collector for fund holdings via Eastmoney's F10 API."""

    API_URL = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"

    # Map report title quarter to month/day
    QUARTER_END = {
        "1": ("03", "31"),
        "2": ("06", "30"),
        "3": ("09", "30"),
        "4": ("12", "31"),
    }

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(
            source_name="eastmoney_fund_f10",
            source_url="https://fundf10.eastmoney.com",
            config=config,
        )
        # Eastmoney F10 endpoints are stable and allow a faster pace than
        # generic institutional websites. Keep a small polite delay.
        self.http.min_delay = 0.5
        self.http.max_delay = 1.5

    def available_report_dates(
        self, product_code: str, **kwargs: Any
    ) -> list[date]:
        """Return available quarterly report dates for the last N years."""
        years = kwargs.get("years", 3)
        current_year = date.today().year
        dates: list[date] = []
        for year in range(current_year - years + 1, current_year + 1):
            for q in ("1", "2", "3", "4"):
                month, day = self.QUARTER_END[q]
                dates.append(date(year, int(month), int(day)))
        return dates

    def collect_holdings(
        self,
        product_code: str,
        product_name: str | None = None,
        report_date: date | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Collect stock holdings for a single fund code.

        Args:
            product_code: Fund code, e.g. "000001".
            product_name: Ignored; only used for logging.
            report_date: If provided, return only the matching quarter.
            **kwargs: Supported keys:
                - years: number of historical years to fetch (default 3)
                - top_n: not used; API always returns top 10
        """
        years = kwargs.get("years", 3)
        target_year = str(report_date.year) if report_date else None
        target_quarter = None
        if report_date:
            target_quarter = str((report_date.month - 1) // 3 + 1)

        reports: list[dict[str, Any]] = []
        current_year = date.today().year
        for year in range(current_year - years + 1, current_year + 1):
            if target_year and str(year) != target_year:
                continue
            year_reports = self._fetch_stock_holdings_for_year(product_code, year)
            for r in year_reports:
                if target_quarter and r["quarter"] != target_quarter:
                    continue
                reports.append(r)

        if not reports:
            return {
                "report_date": report_date,
                "report_type": "quarterly",
                "report_period": None,
                "holdings": [],
                "asset_allocation": [],
                "summary": {},
                "data_source": self.API_URL,
            }

        # If multiple reports matched, pick the latest one for the primary result
        latest = max(reports, key=lambda x: x["report_date"])
        all_holdings: list[dict[str, Any]] = []
        for r in reports:
            for row in r["rows"]:
                all_holdings.append(
                    {
                        "report_date": r["report_date"],
                        "quarter": r["quarter"],
                        **row,
                    }
                )

        # Build asset allocation stub from stock holdings only.
        # Caller can enrich with industry/bond/allocation collectors later.
        asset_allocation = self._build_asset_allocation(latest["rows"])
        summary = self._build_summary(latest["rows"])

        return {
            "report_date": latest["report_date"],
            "report_type": "quarterly",
            "report_period": latest["report_period"],
            "holdings": all_holdings,
            "asset_allocation": asset_allocation,
            "summary": summary,
            "data_source": latest["data_source"],
        }

    def _fetch_stock_holdings_for_year(
        self, product_code: str, year: int
    ) -> list[dict[str, Any]]:
        """Fetch all quarterly stock holding tables for a fund and year."""
        params = {
            "type": "jjcc",
            "code": product_code,
            "topline": 10,
            "year": year,
        }
        response = self.http.get(self.API_URL, params=params)
        text = response.text

        reports: list[dict[str, Any]] = []
        # Split by quarter title. The returned HTML concatenates four tables.
        parts = re.split(
            r'<h4[^>]*>.*?((\d{4})年(\d)季度股票投资明细).*?</h4>', text
        )
        for i in range(1, len(parts), 4):
            title = parts[i]
            q_year = parts[i + 1]
            quarter = parts[i + 2]
            html = parts[i + 3]

            report_date = self._extract_report_date(html, q_year, quarter)
            rows = self._parse_stock_table(html)
            reports.append(
                {
                    "report_date": report_date,
                    "year": q_year,
                    "quarter": quarter,
                    "report_period": title,
                    "rows": rows,
                    "data_source": response.url,
                }
            )
        return reports

    @staticmethod
    def _extract_report_date(html: str, year: str, quarter: str) -> date:
        """Extract report cutoff date from HTML or infer from year/quarter."""
        match = re.search(
            r'截止至：\s*<font[^>]*>(\d{4}-\d{2}-\d{2})</font>', html
        )
        if match:
            parsed = EastmoneyFundHoldingCollector._parse_date_str(match.group(1))
            if parsed:
                return parsed
        month, day = EastmoneyFundHoldingCollector.QUARTER_END[quarter]
        return date(int(year), int(month), int(day))

    @staticmethod
    def _parse_date_str(value: str) -> date | None:
        if not value:
            return None
        from datetime import datetime

        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                return datetime.strptime(value.strip()[:10], fmt).date()
            except ValueError:
                continue
        return None

    def _parse_stock_table(self, html: str) -> list[dict[str, Any]]:
        """Parse a single quarterly stock holding table.

        The column layout changed over time (an extra empty/details column may
        appear), so we identify fields by content rather than fixed indices.
        """
        rows: list[dict[str, Any]] = []
        row_htmls = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S)
        for row_html in row_htmls[1:]:  # skip header
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.S)
            if len(cells) < 7:
                continue
            clean = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            clean = [unescape(c) for c in clean]

            sort_order = self._to_int(clean[0])
            asset_code = clean[1]
            asset_name = clean[2]

            # Identify weight by the percentage sign.
            weight = None
            weight_idx = None
            for idx, c in enumerate(clean):
                if "%" in c:
                    weight = self._to_pct(c)
                    weight_idx = idx
                    break

            # Numeric columns (excluding index 0,1,2 and the weight cell).
            numeric_values: list[tuple[int, float]] = []
            for idx, c in enumerate(clean):
                if idx <= 2 or idx == weight_idx:
                    continue
                val = self._to_float(c)
                if val is not None:
                    numeric_values.append((idx, val))

            # Largest numeric value is market value, second largest is share quantity.
            numeric_values.sort(key=lambda x: x[1], reverse=True)
            market_value = numeric_values[0][1] if numeric_values else None
            share_quantity = numeric_values[1][1] if len(numeric_values) > 1 else None

            rows.append(
                {
                    "sort_order": sort_order,
                    "asset_code": asset_code,
                    "asset_name": asset_name,
                    "weight": weight,
                    "share_quantity": share_quantity,
                    "market_value": market_value,
                    "asset_type": "stock",
                    "sub_type": self._infer_stock_market(asset_code),
                    "market": self._infer_stock_market(asset_code),
                    "is_top10": True,
                    "raw_data": str(clean),
                }
            )
        return rows

    @staticmethod
    def _infer_stock_market(code: str) -> str:
        """Infer A-share market from stock code."""
        code = str(code).strip()
        if not code:
            return "UNKNOWN"
        if code.startswith(("60", "68", "51", "52", "53")):
            return "SH"
        if code.startswith(("00", "30", "39", "12", "08")):
            return "SZ"
        if code.startswith(("8", "4", "43")):
            return "BJ"
        if len(code) == 5:
            return "HK"
        return "UNKNOWN"

    def _to_int(self, value: Any) -> int | None:
        if value is None or str(value).strip() == "":
            return None
        try:
            return int(str(value).strip())
        except ValueError:
            return None

    def _build_asset_allocation(
        self, rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Build a simple asset allocation from stock holdings."""
        total_weight = sum(
            (r.get("weight") or 0) for r in rows if r.get("weight")
        )
        return [
            {
                "asset_class": "stock",
                "weight": total_weight,
                "market_value": sum(
                    (r.get("market_value") or 0) for r in rows
                ),
            }
        ]

    def _build_summary(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Build summary metrics for the latest report."""
        weights = [r.get("weight") or 0 for r in rows]
        top10_weight = sum(weights)
        concentration = sum(w * w for w in weights) if weights else None
        return {
            "top10_weight": top10_weight,
            "stock_weight": top10_weight,
            "holding_count": len(rows),
            "concentration_score": concentration,
        }
