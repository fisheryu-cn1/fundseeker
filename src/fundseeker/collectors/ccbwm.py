"""CCB Wealth Management (建信理财) product list collector.

Uses the official public API endpoint discovered from the website's
JavaScript. This avoids browser automation and is very efficient.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from fundseeker.collectors.base import BaseCollector


class CCBWMCollector(BaseCollector):
    """Collector for CCB Wealth Management (建信理财)."""

    API_URL = "https://www.wealthccb.com/webqueryapp/product/list"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(
            institution_code="JX",
            institution_name="建信理财",
            institution_type="bank_wm",
            list_url="https://www.wealthccb.com/productList.html",
            config=config,
        )

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None or str(value).strip() == "":
            return None
        try:
            return float(str(value).replace(",", ""))
        except ValueError:
            return None

    @staticmethod
    def _parse_date(value: Any) -> date | None:
        if not value:
            return None
        for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(str(value).strip(), fmt).date()
            except ValueError:
                continue
        return None

    def collect_product_list(self) -> list[dict[str, Any]]:
        """Fetch all products from CCB WM public API."""
        payload = json.dumps({"page": 1, "pageSize": 5000})
        response = self.http.post(
            self.API_URL,
            data=payload,
            headers={"Content-Type": "application/json;charset=UTF-8"},
        )
        data = response.json()

        if not data.get("success"):
            raise RuntimeError(
                f"CCB WM API error: {data.get('msg') or data.get('code')}"
            )

        rows = data.get("data", {}).get("list", [])
        products = []
        for row in rows:
            products.append(
                {
                    "product_code": row.get("ivsmpdEcd"),
                    "product_name": row.get("fndNm"),
                    "unit_nav": self._to_float(row.get("accFxMrgnNetval")),
                    "cumulative_nav": self._to_float(row.get("accFxMrgnNetval")),
                    "nav_date": self._parse_date(row.get("drivDt")),
                    "establish_date": self._parse_date(row.get("opdt")),
                    "maturity_date": self._parse_date(row.get("exdt")),
                    "risk_level_raw": row.get("csdcFndRskGrdCd"),
                    "performance_benchmark": row.get("fndPerfcmprbssAmt"),
                    "min_purchase_amount": self._to_float(row.get("pertxnNumLwrlmtVal")),
                    "product_type_raw": row.get("fndIvsDrcCd"),
                    "data_source": self.API_URL,
                    "collect_date": self.today(),
                }
            )
        return products

    def _map_risk_level(self, raw: str | None) -> str:
        """Map CCB WM risk code to standard L1-L5."""
        if not raw:
            return "L3"
        mapping = {
            "R1": "L1",
            "R2": "L2",
            "R3": "L3",
            "R4": "L4",
            "R5": "L5",
        }
        return mapping.get(raw.upper(), "L3")

    def _map_product_type(self, raw: str | None, name: str) -> str:
        """Map CCB WM investment direction code to unified type."""
        # fndIvsDrcCd observed values: 001 固定收益类, 002 权益类, 003 混合类, etc.
        code_map = {
            "001": "fixed_income",
            "002": "equity",
            "003": "mixed",
            "004": "commodity",
            "005": "money_market",
        }
        if raw in code_map:
            return code_map[raw]
        name = name or ""
        if "货币" in name or "现金" in name:
            return "money_market"
        if "债" in name or "固收" in name:
            return "fixed_income"
        if "混合" in name:
            return "mixed"
        if "权益" in name or "股票" in name:
            return "equity"
        return "other"

    def normalize(self, raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Map raw CCB WM rows to the unified product_info schema."""
        risk_mapping = self.config.get("risk_level_mapping", {})

        normalized = []
        for item in raw_items:
            name = item.get("product_name") or ""
            risk_raw = item.get("risk_level_raw") or "R3"
            risk_standard = risk_mapping.get(
                risk_raw, self._map_risk_level(risk_raw)
            )

            normalized.append(
                {
                    "institution_type": self.institution_type,
                    "institution_name": self.institution_name,
                    "institution_code": self.institution_code,
                    "product_code": item.get("product_code"),
                    "product_name": name,
                    "product_short_name": None,
                    "product_type": self._map_product_type(
                        item.get("product_type_raw"), name
                    ),
                    "product_sub_type": item.get("product_type_raw") or None,
                    "registration_code": item.get("product_code"),
                    "sales_code": None,
                    "establish_date": item.get("establish_date"),
                    "maturity_date": item.get("maturity_date"),
                    "risk_level": risk_raw,
                    "risk_level_standard": risk_standard,
                    "currency": "CNY",
                    "manager": self.institution_name,
                    "custodian": "中国建设银行",
                    "fund_manager": None,
                    "investment_target": None,
                    "investment_scope": None,
                    "investment_strategy": None,
                    "performance_benchmark": item.get("performance_benchmark"),
                    "benchmark_type": None,
                    "min_purchase_amount": item.get("min_purchase_amount"),
                    "min_additional_amount": None,
                    "status": "active",
                    "data_source": item.get("data_source", self.API_URL),
                    "collect_date": item.get("collect_date") or date.today(),
                }
            )
        return normalized
