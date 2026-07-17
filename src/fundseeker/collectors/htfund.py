"""Hua Tian / China Universal (汇添富基金) product list collector."""

from __future__ import annotations

from typing import Any

from fundseeker.collectors.fund_company import FundCompanyCollector


class HTFundCollector(FundCompanyCollector):
    """Collector for China Universal Asset Management (汇添富基金)."""

    EASTMONEY_GS_ID = "80053708"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(
            institution_code="HTF",
            institution_name="汇添富基金",
            list_url="https://www.99fund.com/main/products/jijinhb/index.shtml",
            config=config,
        )
