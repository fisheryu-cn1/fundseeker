"""CEB Wealth Management (光大理财) product list collector.

Lightweight implementation using China Wealth Network's public
recommendation JSON endpoints. These endpoints return only a small
sample of featured products (around 10 per category) and do not cover
the full product catalog. Full coverage requires either:
- Playwright interaction with the China Wealth screening page (captcha)
- Reverse-engineering the encrypted /lcw-fe-service/prod/search API
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fundseeker.collectors.base import BaseCollector


class CEBWMCollector(BaseCollector):
    """Collector for CEB Wealth Management (光大理财) via China Wealth Network."""

    JSON_URLS = [
        "https://www.chinawealth.com.cn/wealthprod/durationProduct_EN.json",
        "https://www.chinawealth.com.cn/wealthprod/retireProduct_EN.json",
    ]

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(
            institution_code="CEB",
            institution_name="光大理财",
            institution_type="bank_wm",
            list_url="https://www.chinawealth.com.cn/lcweb/management/proScreen",
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
    def _extract_risk_level(risk_text: str | None) -> str:
        if not risk_text:
            return "R3"
        risk_text = risk_text.strip().upper()
        if "R1" in risk_text or "一级" in risk_text or "低" in risk_text:
            return "R1"
        if "R2" in risk_text or "二级" in risk_text or "中低" in risk_text:
            return "R2"
        if "R4" in risk_text or "四级" in risk_text or "中高" in risk_text:
            return "R4"
        if "R5" in risk_text or "五级" in risk_text or "高" in risk_text:
            return "R5"
        return "R3"

    @staticmethod
    def _map_product_type(name: str) -> str:
        name = name or ""
        if "养老" in name:
            return "fof"
        if "固收" in name or "债" in name or "丰利" in name:
            return "fixed_income"
        if "混合" in name or "混" in name:
            return "mixed"
        if "权益" in name or "股票" in name:
            return "equity"
        if "现金" in name or "天天" in name:
            return "money_market"
        return "other"

    def collect_product_list(self) -> list[dict[str, Any]]:
        """Fetch featured CEB WM products from China Wealth Network JSON endpoints."""
        headers = {
            "Referer": "https://www.chinawealth.com.cn/",
        }

        seen: set[str] = set()
        products: list[dict[str, Any]] = []

        for url in self.JSON_URLS:
            response = self.safe_get(url, headers=headers)
            rows = response.json()
            if not isinstance(rows, list):
                continue

            for row in rows:
                org_name = row.get("orgName") or ""
                if "光大理财" not in org_name:
                    continue

                code = row.get("prodRegCode")
                if not code or code in seen:
                    continue
                seen.add(code)

                products.append(
                    {
                        "product_code": code,
                        "product_name": row.get("prodName"),
                        "risk_level_raw": self._extract_risk_level(
                            row.get("prodRiskLevelName")
                        ),
                        "product_type_raw": row.get("prodOperateModeName"),
                        "registration_code": code,
                        "data_source": url,
                        "collect_date": self.today(),
                    }
                )

        return products

    def normalize(self, raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Map raw CEB WM rows to the unified product_info schema."""
        risk_mapping = self.config.get("risk_level_mapping", {})

        normalized = []
        for item in raw_items:
            name = item.get("product_name") or ""
            risk_raw = item.get("risk_level_raw") or "R3"
            risk_standard = risk_mapping.get(risk_raw, self._extract_risk_level(risk_raw))

            normalized.append(
                {
                    "institution_type": self.institution_type,
                    "institution_name": self.institution_name,
                    "institution_code": self.institution_code,
                    "product_code": item.get("product_code"),
                    "product_name": name,
                    "product_short_name": None,
                    "product_type": self._map_product_type(name),
                    "product_sub_type": item.get("product_type_raw") or None,
                    "registration_code": item.get("registration_code"),
                    "sales_code": None,
                    "establish_date": None,
                    "maturity_date": None,
                    "risk_level": risk_raw,
                    "risk_level_standard": risk_standard,
                    "currency": "CNY",
                    "manager": self.institution_name,
                    "custodian": "中国光大银行",
                    "fund_manager": None,
                    "investment_target": None,
                    "investment_scope": None,
                    "investment_strategy": None,
                    "performance_benchmark": None,
                    "benchmark_type": None,
                    "min_purchase_amount": None,
                    "min_additional_amount": None,
                    "status": "active",
                    "data_source": item.get("data_source", self.JSON_URLS[0]),
                    "collect_date": item.get("collect_date") or date.today(),
                }
            )
        return normalized
