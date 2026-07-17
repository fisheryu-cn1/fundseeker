"""CITIC Wealth Management (信银理财) product list collector.

Uses the official public API endpoint from the WeChat distribution site.
No signature or login is required.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fundseeker.collectors.base import BaseCollector


class CITICWMCollector(BaseCollector):
    """Collector for CITIC Wealth Management (信银理财)."""

    API_URL = "https://wechat.citic-wealth.com/cms.product/api/custom/productInfo/fundList"

    PRODUCT_TYPES = [1, 2, 3, 4, 5]
    SALE_CUSTOMS = [0]

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(
            institution_code="CITIC",
            institution_name="信银理财",
            institution_type="bank_wm",
            list_url="https://www.citic-wealth.com/yymk/lccs/",
            config=config,
            ssl_legacy=True,
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
        text = str(value).strip()[:10]
        for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _extract_risk_level(risk_value: int | str | None) -> str:
        if risk_value is None:
            return "R3"
        mapping = {
            1: "R1",
            2: "R2",
            3: "R3",
            4: "R4",
            5: "R5",
        }
        if isinstance(risk_value, int):
            return mapping.get(risk_value, "R3")
        text = str(risk_value).strip().upper()
        if "R1" in text or "PR1" in text:
            return "R1"
        if "R2" in text or "PR2" in text:
            return "R2"
        if "R4" in text or "PR4" in text:
            return "R4"
        if "R5" in text or "PR5" in text:
            return "R5"
        return "R3"

    @staticmethod
    def _map_product_type(raw: str | None, name: str) -> str:
        raw = (raw or "").strip()
        name = name or ""
        if "货币" in raw or "现金" in name or "每日购" in raw:
            return "money_market"
        if "固收" in raw or "债" in name:
            return "fixed_income"
        if "混合" in raw or "混" in raw:
            return "mixed"
        if "权益" in raw or "股票" in raw:
            return "equity"
        if "指数" in raw or "ETF" in name.upper():
            return "index"
        if "QDII" in name.upper():
            return "qdii"
        if "商品" in raw or "衍生" in raw:
            return "commodity"
        return "other"

    def _fetch_page(
        self, product_type: int, sale_custom: int, page_num: int, page_size: int = 200
    ) -> dict[str, Any]:
        params = {
            "pageNum": page_num,
            "pageSize": page_size,
            "productType": product_type,
            "prodSaleCustom": sale_custom,
        }
        response = self.http.get(self.API_URL, params=params)
        data = response.json()

        if data.get("code") != "0000":
            raise RuntimeError(
                f"CITIC WM API error (type={product_type}, custom={sale_custom}): {data.get('msg')}"
            )

        return data.get("data", {})

    def collect_product_list(self) -> list[dict[str, Any]]:
        """Fetch all products from CITIC WM public API."""
        products_map: dict[str, dict[str, Any]] = {}

        for sale_custom in self.SALE_CUSTOMS:
            for product_type in self.PRODUCT_TYPES:
                page = 1
                while True:
                    data = self._fetch_page(product_type, sale_custom, page)
                    records = data.get("records", [])
                    for item in records:
                        code = item.get("prodCode")
                        if not code:
                            continue
                        # Keep the first occurrence; personal (0) usually has
                        # richer fields than institutional (1).
                        if code not in products_map:
                            products_map[code] = {
                                "product_code": code,
                                "product_name": item.get("prodName"),
                                "product_short_name": item.get("prodNameShort"),
                                "risk_level_raw": self._extract_risk_level(
                                    item.get("riskLevel")
                                ),
                                "product_type_raw": item.get("profitTypeStr"),
                                "product_sub_type": item.get("respProductTypeStr"),
                                "establish_date": self._parse_date(
                                    item.get("establishDateStr")
                                ),
                                "unit_nav": self._to_float(item.get("nav")),
                                "cumulative_nav": self._to_float(item.get("totalNav")),
                                "nav_date": self._parse_date(item.get("navDate")),
                                "performance_benchmark": item.get("benchmarks"),
                                "min_purchase_amount": self._to_float(
                                    item.get("minSubsP")
                                ),
                                "min_additional_amount": self._to_float(
                                    item.get("minApplyP")
                                ),
                                "data_source": self.API_URL,
                                "collect_date": self.today(),
                            }

                    total_pages = data.get("pages", 1)
                    if page >= total_pages or not records:
                        break
                    page += 1

        return list(products_map.values())

    def normalize(self, raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Map raw CITIC WM rows to the unified product_info schema."""
        risk_mapping = self.config.get("risk_level_mapping", {})

        normalized = []
        for item in raw_items:
            name = item.get("product_name") or ""
            risk_raw = item.get("risk_level_raw") or "R3"
            risk_standard = risk_mapping.get(risk_raw, risk_raw)

            normalized.append(
                {
                    "institution_type": self.institution_type,
                    "institution_name": self.institution_name,
                    "institution_code": self.institution_code,
                    "product_code": item.get("product_code"),
                    "product_name": name,
                    "product_short_name": item.get("product_short_name"),
                    "product_type": self._map_product_type(
                        item.get("product_type_raw"), name
                    ),
                    "product_sub_type": item.get("product_sub_type") or None,
                    "registration_code": item.get("product_code"),
                    "sales_code": None,
                    "establish_date": item.get("establish_date"),
                    "maturity_date": None,
                    "risk_level": risk_raw,
                    "risk_level_standard": risk_standard,
                    "currency": "CNY",
                    "manager": self.institution_name,
                    "custodian": "中信银行",
                    "fund_manager": None,
                    "investment_target": None,
                    "investment_scope": None,
                    "investment_strategy": None,
                    "performance_benchmark": item.get("performance_benchmark"),
                    "benchmark_type": None,
                    "min_purchase_amount": item.get("min_purchase_amount"),
                    "min_additional_amount": item.get("min_additional_amount"),
                    "status": "active",
                    "data_source": item.get("data_source", self.API_URL),
                    "collect_date": item.get("collect_date") or date.today(),
                }
            )
        return normalized
