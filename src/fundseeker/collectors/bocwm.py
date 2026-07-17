"""BOC Wealth Management (中银理财) product list collector.

Uses the official public API endpoint discovered from the website's
JavaScript. The endpoint returns both product metadata and latest NAV.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fundseeker.collectors.base import BaseCollector


class BOCWMCollector(BaseCollector):
    """Collector for BOC Wealth Management (中银理财)."""

    API_URL = "https://www.bocwm.cn/webApi/cms/product/queryStaticProducts"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(
            institution_code="BOC",
            institution_name="中银理财",
            institution_type="bank_wm",
            list_url="https://www.bocwm.cn/html/1//151/222/index.html",
            config=config,
        )

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None or str(value).strip() in ("", "--", "---"):
            return None
        try:
            return float(str(value).replace(",", ""))
        except ValueError:
            return None

    @staticmethod
    def _parse_date(value: Any) -> date | None:
        if not value:
            return None
        text = str(value).strip()[:10]
        for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return None

    def _extract_risk_level(self, risk_text: str | None) -> str:
        if not risk_text:
            return "R3"
        risk_text = risk_text.strip().upper()
        if "R1" in risk_text or "低" in risk_text:
            return "R1"
        if "R2" in risk_text or "中低" in risk_text:
            return "R2"
        if "R4" in risk_text or "中高" in risk_text:
            return "R4"
        if "R5" in risk_text or "高" in risk_text:
            return "R5"
        return "R3"

    def _map_product_type(self, name: str) -> str:
        name = name or ""
        if "现金" in name or "天天" in name or "日日开" in name:
            return "money_market"
        if "固收" in name or "债" in name or "稳富" in name:
            return "fixed_income"
        if "混合" in name or "混" in name:
            return "mixed"
        if "权益" in name or "股票" in name or "智富" in name:
            return "equity"
        if "指数" in name or "ETF" in name.upper():
            return "index"
        if "QDII" in name.upper() or "全球" in name:
            return "qdii"
        if "商品" in name or "衍生" in name:
            return "commodity"
        return "other"

    def collect_product_list(self) -> list[dict[str, Any]]:
        """Fetch all products from BOC WM public API."""
        payload = {
            "style": "",
            "timeLimit": "",
            "riskLevel": "",
            "currency": "",
            "productTypeName": "",
            "productClass": [],
            "investorRange": "机构产品",
            "productKeyword": "",
            "pageNo": 1,
            "pageSize": 2000,
        }
        response = self.http.post(
            self.API_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "X-CSRF-TOKEN": "csrfToken",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": self.list_url,
                "Origin": "https://www.bocwm.cn",
            },
        )
        data = response.json()

        if not data.get("result"):
            raise RuntimeError(
                f"BOC WM API error: {data.get('msg') or data.get('code')}"
            )

        rows = data.get("data", {}).get("rows", [])
        products = []
        for row in rows:
            products.append(
                {
                    "product_code": row.get("productCode"),
                    "product_name": row.get("productName"),
                    "unit_nav": self._to_float(row.get("shareNetWorth")),
                    "cumulative_nav": self._to_float(row.get("cumulativeNetWorth")),
                    "nav_date": self._parse_date(row.get("releaseDate")),
                    "risk_level_raw": self._extract_risk_level(row.get("riskLevel")),
                    "min_purchase_amount": self._to_float(row.get("startsPrice")),
                    "product_detail_url": row.get("productDetailUrl"),
                    "data_source": self.API_URL,
                    "collect_date": self.today(),
                }
            )
        return products

    def normalize(self, raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Map raw BOC WM rows to the unified product_info schema."""
        risk_mapping = self.config.get("risk_level_mapping", {})

        normalized = []
        for item in raw_items:
            name = item.get("product_name") or ""
            risk_raw = item.get("risk_level_raw") or "R3"
            risk_standard = risk_mapping.get(risk_raw, f"L{risk_raw[-1]}")

            normalized.append(
                {
                    "institution_type": self.institution_type,
                    "institution_name": self.institution_name,
                    "institution_code": self.institution_code,
                    "product_code": item.get("product_code"),
                    "product_name": name,
                    "product_short_name": None,
                    "product_type": self._map_product_type(name),
                    "product_sub_type": None,
                    "registration_code": item.get("product_code"),
                    "sales_code": None,
                    "establish_date": None,
                    "maturity_date": None,
                    "risk_level": risk_raw,
                    "risk_level_standard": risk_standard,
                    "currency": "CNY",
                    "manager": self.institution_name,
                    "custodian": "中国银行",
                    "fund_manager": None,
                    "investment_target": None,
                    "investment_scope": None,
                    "investment_strategy": None,
                    "performance_benchmark": None,
                    "benchmark_type": None,
                    "min_purchase_amount": item.get("min_purchase_amount"),
                    "min_additional_amount": None,
                    "status": "active",
                    "data_source": item.get("data_source", self.API_URL),
                    "collect_date": item.get("collect_date") or date.today(),
                }
            )
        return normalized
