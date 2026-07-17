"""E Fund (易方达基金) product list collector."""

from __future__ import annotations

from typing import Any

from fundseeker.collectors.fund_company import FundCompanyCollector


class EFundCollector(FundCompanyCollector):
    """Collector for E Fund Management (易方达基金)."""

    EASTMONEY_GS_ID = "80000229"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(
            institution_code="YFD",
            institution_name="易方达基金",
            list_url="https://www.efunds.com.cn/lm/jjcp/",
            config=config,
        )
