"""SPDB Wealth Management (浦银理财) product list collector.

Uses the official public API endpoint discovered from the website's
JavaScript. The endpoint returns product metadata and latest NAV in
separate channels.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fundseeker.collectors.base import BaseCollector


class SPDBWMCollector(BaseCollector):
    """Collector for SPDB Wealth Management (浦银理财)."""

    API_URL = "https://www.spdb-wm.com/api/search"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(
            institution_code="SPD",
            institution_name="浦银理财",
            institution_type="bank_wm",
            list_url="https://www.spdb-wm.com/financialProducts/",
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
        text = str(value).strip()
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
        if "R2" in risk_text or "中低" in risk_text or "较低" in risk_text:
            return "R2"
        if "R4" in risk_text or "中高" in risk_text or "较高" in risk_text:
            return "R4"
        if "R5" in risk_text or "高" in risk_text:
            return "R5"
        return "R3"

    def _map_product_type(self, raw: str | None, name: str) -> str:
        raw = (raw or "").strip()
        name = name or ""
        if "货币" in raw or "现金" in name or "天天" in name:
            return "money_market"
        if "固收" in raw or "债" in raw:
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

    def _fetch_channel(self, chlid: int, size: int = 99999) -> list[dict[str, Any]]:
        payload = {
            "chlid": chlid,
            "cutsize": 150,
            "dynexpr": [],
            "dynidx": 1,
            "extopt": [],
            "orderby": "",
            "page": 1,
            "size": size,
            "searchword": "",
        }
        response = self.http.post(self.API_URL, json=payload)
        data = response.json()

        if data.get("code") != 20000:
            raise RuntimeError(
                f"SPDB WM API error (chlid={chlid}): {data.get('message') or data.get('code')}"
            )

        return data.get("data", {}).get("content", [])

    def collect_product_list(self) -> list[dict[str, Any]]:
        """Fetch all products and latest NAV from SPDB WM public API."""
        products = self._fetch_channel(1002)
        nav_rows = self._fetch_channel(1006)

        nav_map = {}
        for nav in nav_rows:
            code = nav.get("REAL_PRD_CODE")
            if code and code not in nav_map:
                nav_map[code] = nav

        merged = []
        for prod in products:
            code = prod.get("PRDC_CD")
            nav = nav_map.get(code, {})
            merged.append(
                {
                    "product_code": code,
                    "product_name": prod.get("PRDC_NM"),
                    "product_form": prod.get("PRDC_FRM"),
                    "risk_level_raw": prod.get("RISK_GRADE"),
                    "product_type_raw": prod.get("PRDC_TYP"),
                    "product_status": prod.get("PRDC_STT"),
                    "sales_object": prod.get("SLL_OBJC"),
                    "term_type": prod.get("TERM_TYPE"),
                    "registration_code": prod.get("PRDC_RGST_CD"),
                    "currency": prod.get("RS_CRRN") or "CNY",
                    "unit_nav": self._to_float(nav.get("NAV")),
                    "cumulative_nav": self._to_float(nav.get("TOT_NAV")),
                    "nav_date": self._parse_date(nav.get("ISS_DATE")),
                    "data_source": self.API_URL,
                    "collect_date": self.today(),
                }
            )
        return merged

    def normalize(self, raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Map raw SPDB WM rows to the unified product_info schema."""
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
                    "product_type": self._map_product_type(
                        item.get("product_type_raw"), name
                    ),
                    "product_sub_type": item.get("product_type_raw") or None,
                    "registration_code": item.get("registration_code"),
                    "sales_code": None,
                    "establish_date": None,
                    "maturity_date": None,
                    "risk_level": risk_raw,
                    "risk_level_standard": risk_standard,
                    "currency": item.get("currency", "CNY"),
                    "manager": self.institution_name,
                    "custodian": "上海浦东发展银行",
                    "fund_manager": None,
                    "investment_target": None,
                    "investment_scope": None,
                    "investment_strategy": None,
                    "performance_benchmark": None,
                    "benchmark_type": None,
                    "min_purchase_amount": None,
                    "min_additional_amount": None,
                    "status": "active" if (item.get("product_status") or "") != "终止" else "inactive",
                    "data_source": item.get("data_source", self.API_URL),
                    "collect_date": item.get("collect_date") or date.today(),
                }
            )
        return normalized
