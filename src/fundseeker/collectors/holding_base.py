"""Base class for holding/portfolio collectors.

Holding collectors are responsible for fetching portfolio composition data
(product holdings, asset allocation, top positions) for already-collected
products. They operate on product identifiers rather than scraping product
lists from scratch.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any

from fundseeker.utils.http import PoliteHttpClient


class HoldingCollector(ABC):
    """Abstract base class for portfolio holding collectors."""

    def __init__(
        self,
        source_name: str,
        source_url: str,
        config: dict[str, Any] | None = None,
        ssl_legacy: bool = False,
    ):
        self.source_name = source_name
        self.source_url = source_url
        self.config = config or {}

        request_cfg = self.config.get("request", {})
        self.http = PoliteHttpClient(
            user_agent=self.config.get("global", {}).get("user_agent"),
            min_delay=request_cfg.get(
                "min_delay_seconds",
                self.config.get("global", {}).get("default_min_delay", 5.0),
            ),
            max_delay=request_cfg.get(
                "max_delay_seconds",
                self.config.get("global", {}).get("default_max_delay", 10.0),
            ),
            max_retries=request_cfg.get("max_retries", 3),
            timeout=request_cfg.get("timeout", 30),
            respect_robots_txt=self.config.get("global", {}).get(
                "respect_robots_txt", True
            ),
            ssl_legacy=ssl_legacy,
        )

    @abstractmethod
    def collect_holdings(
        self,
        product_code: str,
        product_name: str | None = None,
        report_date: date | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Collect holding data for a single product.

        Args:
            product_code: External product code (e.g. fund code).
            product_name: Optional product name for logging/diagnostics.
            report_date: Optional target report date. If None, use the latest.
            **kwargs: Source-specific parameters (year, top_n, etc.).

        Returns:
            A dictionary with standardized keys:
                - "report_date": date
                - "report_type": str (quarterly/annual/interim)
                - "report_period": str (human readable, e.g. "2024年4季度")
                - "holdings": list[dict] with holding detail rows
                - "asset_allocation": list[dict] with asset class weights
                - "summary": dict with derived metrics
                - "data_source": str
        """
        ...

    @abstractmethod
    def available_report_dates(
        self, product_code: str, **kwargs: Any
    ) -> list[date]:
        """Return available report dates for a product."""
        ...

    def _to_float(self, value: Any) -> float | None:
        """Safely convert a value to float."""
        if value is None or str(value).strip() in ("", "---", "--"):
            return None
        try:
            return float(str(value).replace(",", "").replace("%", ""))
        except ValueError:
            return None

    def _to_pct(self, value: Any) -> float | None:
        """Convert a percentage string to decimal (e.g. '8.5%' -> 0.085)."""
        if value is None or str(value).strip() in ("", "---", "--"):
            return None
        text = str(value).strip().replace(",", "")
        try:
            if "%" in text:
                return float(text.replace("%", "")) / 100.0
            return float(text)
        except ValueError:
            return None

    def _parse_date(self, value: Any) -> date | None:
        """Parse a date string into a date object."""
        if not value:
            return None
        from datetime import datetime as _dt

        text = str(value).strip()[:10]
        for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
            try:
                return _dt.strptime(text, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def standardize_holding_row(row: dict[str, Any]) -> dict[str, Any]:
        """Normalize a raw holding row to the unified schema.

        Subclasses may call this after extracting source-specific fields.
        """
        return {
            "asset_code": row.get("asset_code"),
            "asset_name": row.get("asset_name", ""),
            "asset_type": row.get("asset_type", "other"),
            "sub_type": row.get("sub_type"),
            "market": row.get("market"),
            "issuer_name": row.get("issuer_name"),
            "industry_code": row.get("industry_code"),
            "industry_name": row.get("industry_name"),
            "weight": row.get("weight"),
            "market_value": row.get("market_value"),
            "share_quantity": row.get("share_quantity"),
            "cost_basis": row.get("cost_basis"),
            "valuation_method": row.get("valuation_method"),
            "is_top10": bool(row.get("is_top10", False)),
            "sort_order": row.get("sort_order"),
            "raw_data": row.get("raw_data"),
        }
