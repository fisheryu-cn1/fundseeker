"""GF Fund Management (广发基金) product list collector."""

from __future__ import annotations

from typing import Any

from fundseeker.collectors.fund_company import FundCompanyCollector


class GFFundCollector(FundCompanyCollector):
    """Collector for GF Fund Management (广发基金)."""

    EASTMONEY_GS_ID = "80000248"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(
            institution_code="GF",
            institution_name="广发基金",
            list_url="https://www.gffunds.com.cn/",
            config=config,
        )
