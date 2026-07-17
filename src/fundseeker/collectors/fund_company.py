"""Generic collector for public fund companies via Eastmoney.

This collector uses Eastmoney's public fund list endpoint to fetch all funds
under a specific fund company. It avoids direct crawling of official websites
and implements polite request pacing.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import json5

from fundseeker.collectors.base import BaseCollector


class FundCompanyCollector(BaseCollector):
    """Generic collector for a fund company using Eastmoney public API."""

    # Override in subclass
    EASTMONEY_GS_ID: str = ""

    def __init__(
        self,
        institution_code: str,
        institution_name: str,
        list_url: str,
        config: dict[str, Any] | None = None,
    ):
        super().__init__(
            institution_code=institution_code,
            institution_name=institution_name,
            institution_type="fund_company",
            list_url=list_url,
            config=config,
        )
        self.eastmoney_list_url = (
            "http://fund.eastmoney.com/Data/Fund_JJJZ_Data.aspx"
            f"?t=1&lx=1&letter=&gsid={self.EASTMONEY_GS_ID}&text="
            "&sort=zdf,desc&page=1,9999&dt=1463790518010&atfc=%2526onlySale=0"
        )

    @staticmethod
    def _to_float(value: str) -> float | None:
        """Convert Eastmoney empty marker to None, otherwise float."""
        if value is None or str(value).strip() in ("", "---"):
            return None
        try:
            return float(str(value).replace(",", ""))
        except ValueError:
            return None

    def collect_product_list(self) -> list[dict[str, Any]]:
        """Fetch fund list from Eastmoney public API."""
        response = self.safe_get(self.eastmoney_list_url)
        text = response.text

        prefix = "var db="
        if not text.startswith(prefix):
            raise ValueError("Unexpected Eastmoney response prefix")

        data = json5.loads(text[len(prefix):])
        rows = data.get("datas", [])

        products = []
        for row in rows:
            if len(row) < 8:
                continue
            products.append(
                {
                    "product_code": row[0],
                    "product_name": row[1],
                    "product_type_raw": row[2] if len(row) > 2 else "",
                    "unit_nav": self._to_float(row[5]),
                    "cumulative_nav": self._to_float(row[6]),
                    "daily_return": self._to_float(row[7]),
                    "return_1m": self._to_float(row[10]) if len(row) > 10 else None,
                    "return_3m": self._to_float(row[11]) if len(row) > 11 else None,
                    "return_6m": self._to_float(row[12]) if len(row) > 12 else None,
                    "return_1y": self._to_float(row[13]) if len(row) > 13 else None,
                    "data_source": self.eastmoney_list_url,
                    "collect_date": self.today(),
                }
            )
        return products

    @staticmethod
    def _infer_product_type(name: str) -> str:
        """Infer unified product type from Chinese fund name."""
        name = name or ""
        if "货币" in name or "余额宝" in name or "现金" in name:
            return "money_market"
        if "QDII" in name.upper():
            return "qdii"
        if "FOF" in name.upper():
            return "fof"
        if "ETF" in name.upper() or "指数" in name or "联接" in name:
            return "index"
        if "债" in name or "纯债" in name or "短债" in name or "固收" in name:
            return "fixed_income"
        if "混合" in name or "偏股" in name or "灵活配置" in name:
            return "mixed"
        if "股票" in name or "权益" in name:
            return "equity"
        return "other"

    def normalize(self, raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Map raw Eastmoney rows to the unified product_info schema."""
        risk_mapping = self.config.get("risk_level_mapping", {})

        normalized = []
        for item in raw_items:
            name = item.get("product_name") or ""
            product_type = self._infer_product_type(name)

            normalized.append(
                {
                    "institution_type": self.institution_type,
                    "institution_name": self.institution_name,
                    "institution_code": self.institution_code,
                    "product_code": item.get("product_code"),
                    "product_name": name,
                    "product_short_name": None,
                    "product_type": product_type,
                    "product_sub_type": item.get("product_type_raw") or None,
                    "registration_code": None,
                    "sales_code": None,
                    "establish_date": None,
                    "maturity_date": None,
                    "risk_level": "R3",
                    "risk_level_standard": risk_mapping.get("R3", "L3"),
                    "currency": "CNY",
                    "manager": self.institution_name,
                    "custodian": None,
                    "fund_manager": None,
                    "investment_target": None,
                    "investment_scope": None,
                    "investment_strategy": None,
                    "performance_benchmark": None,
                    "benchmark_type": None,
                    "min_purchase_amount": None,
                    "min_additional_amount": None,
                    "status": "active",
                    "data_source": item.get("data_source", self.eastmoney_list_url),
                    "collect_date": item.get("collect_date") or date.today(),
                }
            )
        return normalized
