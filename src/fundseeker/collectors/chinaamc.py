"""China Asset Management (华夏基金) product list collector."""

from __future__ import annotations

from typing import Any

from fundseeker.collectors.fund_company import FundCompanyCollector


class ChinaAMCCollector(FundCompanyCollector):
    """Collector for China Asset Management (华夏基金)."""

    EASTMONEY_GS_ID = "80000222"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(
            institution_code="ChinaAMC",
            institution_name="华夏基金",
            list_url="https://www.chinaamc.com/",
            config=config,
        )
