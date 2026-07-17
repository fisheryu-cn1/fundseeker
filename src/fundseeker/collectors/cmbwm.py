"""CMB Wealth Management (招银理财 via CMB distribution site) collector.

Uses Playwright to interact with the CMB distribution page. The site uses
signed API requests, so direct HTTP calls are not feasible; instead we let
the browser make the requests and intercept the JSON responses.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from typing import Any

from fundseeker.collectors.base import BaseCollector


class CMBWMCollector(BaseCollector):
    """Collector for CMB Wealth Management (招银理财) via CMB distribution page."""

    PAGE_URL = "https://cfweb.paas.cmbchina.com/corporate/ProdBySeries?code=020186"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(
            institution_code="ZY",
            institution_name="招银理财",
            institution_type="bank_wm",
            list_url=self.PAGE_URL,
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

    def collect_product_list(self) -> list[dict[str, Any]]:
        """Collect product list by driving the CMB distribution page."""
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is required for CMBWM collector. "
                "Install it with: pip install playwright && playwright install chromium"
            ) from exc

        return asyncio.run(self._collect_async())

    async def _collect_async(self) -> list[dict[str, Any]]:
        from playwright.async_api import async_playwright

        products: list[dict[str, Any]] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            captured_responses: list[dict] = []

            async def handle_response(response):
                if "getProductByFilterByPage" in response.url:
                    try:
                        body = await response.body()
                        data = json.loads(body.decode("utf-8"))
                        captured_responses.append(data)
                    except Exception:
                        pass

            page.on("response", handle_response)

            await page.goto(
                self.PAGE_URL, wait_until="networkidle", timeout=60000
            )
            await asyncio.sleep(3)

            # Click "查看更多" to expand the series list and trigger first load.
            more = await page.query_selector("text=查看更多")
            if more:
                await more.click()
                await asyncio.sleep(5)

            # Collect products from the default series load.
            products.extend(self._extract_from_responses(captured_responses))
            captured_responses.clear()

            # Get all 招银理财 series links.
            # Note: the distribution site uses lowercase 'prodbyseries' and
            # includes a 'maintype' query parameter.
            series_links = await page.query_selector_all(
                'a[href*="/corporate/prodbyseries?maintype="]'
            )
            zy_links: list[tuple[str, str]] = []
            for link in series_links:
                href = await link.get_attribute("href")
                text = await link.inner_text()
                if href and "code=" in href and text.strip().startswith("招"):
                    zy_links.append((href, text.strip()))

            # The page already starts at the first series; skip re-clicking it.
            current_code = "020186"
            zy_links = [
                (href, text)
                for href, text in zy_links
                if current_code not in href
            ]

            # Process first N series to keep runtime reasonable.
            # Full traversal is possible but slow due to signed API pacing.
            max_series = self.config.get("cmbwm", {}).get("max_series", 5)
            wait_seconds = self.config.get("cmbwm", {}).get("wait_seconds", 3)
            for idx, (href, _) in enumerate(zy_links):
                if idx >= max_series:
                    break
                try:
                    await page.evaluate(
                        f"""() => {{
                            const link = document.querySelector('a[href="{href}"]');
                            if (link) link.click();
                        }}"""
                    )
                    await asyncio.sleep(wait_seconds)
                    products.extend(
                        self._extract_from_responses(captured_responses)
                    )
                    captured_responses.clear()
                except Exception:
                    continue

            await browser.close()

        # Deduplicate by product code.
        seen: set[str] = set()
        unique_products = []
        for p in products:
            code = p.get("product_code")
            if code and code not in seen:
                seen.add(code)
                unique_products.append(p)

        return unique_products

    def _extract_from_responses(
        self, responses: list[dict]
    ) -> list[dict[str, Any]]:
        products = []
        for resp in responses:
            body = resp.get("body", {})
            for item in body.get("data", []):
                products.append(
                    {
                        "product_code": item.get("prdCode"),
                        "product_name": item.get("prdName") or item.get("prdBrief"),
                        "unit_nav": self._to_float(item.get("netValue")),
                        "cumulative_nav": None,
                        "nav_date": self.today(),
                        "establish_date": self._parse_date(item.get("beginDate")),
                        "maturity_date": self._parse_date(item.get("expireDate")),
                        "risk_level_raw": self._extract_risk_level(
                            item.get("risk")
                        ),
                        "performance_benchmark": item.get("rateDes") or None,
                        "min_purchase_amount": self._to_float(
                            item.get("initMoney")
                        ),
                        "product_type_raw": item.get("style"),
                        "registration_code": item.get("regCode"),
                        "data_source": self.PAGE_URL,
                        "collect_date": self.today(),
                    }
                )
        return products

    def _map_product_type(self, raw: str | None, name: str) -> str:
        name = name or ""
        raw = (raw or "").strip()
        if "现金" in raw or "货币" in name:
            return "money_market"
        if "固收" in raw or "债" in name or "封闭" in name:
            return "fixed_income"
        if "混合" in raw or "混" in name:
            return "mixed"
        if "权益" in raw or "股票" in name:
            return "equity"
        if "指数" in raw or "ETF" in name.upper():
            return "index"
        if "QDII" in name.upper():
            return "qdii"
        return "other"

    def normalize(self, raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Map raw CMB WM rows to the unified product_info schema."""
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
                    "product_type": self._map_product_type(
                        item.get("product_type_raw"), name
                    ),
                    "product_sub_type": item.get("product_type_raw") or None,
                    "registration_code": item.get("registration_code"),
                    "sales_code": None,
                    "establish_date": item.get("establish_date"),
                    "maturity_date": item.get("maturity_date"),
                    "risk_level": risk_raw,
                    "risk_level_standard": risk_standard,
                    "currency": "CNY",
                    "manager": self.institution_name,
                    "custodian": "招商银行",
                    "fund_manager": None,
                    "investment_target": None,
                    "investment_scope": None,
                    "investment_strategy": None,
                    "performance_benchmark": item.get("performance_benchmark"),
                    "benchmark_type": None,
                    "min_purchase_amount": item.get("min_purchase_amount"),
                    "min_additional_amount": None,
                    "status": "active",
                    "data_source": item.get("data_source", self.PAGE_URL),
                    "collect_date": item.get("collect_date") or date.today(),
                }
            )
        return normalized
