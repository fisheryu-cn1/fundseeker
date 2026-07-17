"""Base collector interface and shared helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any

from fundseeker.utils.http import PoliteHttpClient


class BaseCollector(ABC):
    """Abstract base class for all institution collectors."""

    def __init__(
        self,
        institution_code: str,
        institution_name: str,
        institution_type: str,
        list_url: str,
        config: dict[str, Any] | None = None,
        ssl_legacy: bool = False,
    ):
        self.institution_code = institution_code
        self.institution_name = institution_name
        self.institution_type = institution_type
        self.list_url = list_url
        self.config = config or {}

        # Locate per-institution request settings when the full config object is
        # passed; fall back to a top-level "request" block or global defaults.
        request_cfg = self.config.get("request", {})
        for inst in self.config.get("institutions", []):
            if inst.get("code") == institution_code:
                request_cfg = inst.get("request", request_cfg)
                break

        self.http = PoliteHttpClient(
            user_agent=self.config.get("global", {}).get("user_agent"),
            min_delay=request_cfg.get(
                "min_delay_seconds",
                self.config.get("global", {}).get("default_min_delay", 5.0),
            ),
            max_delay=request_cfg.get(
                "max_delay_seconds",
                self.config.get("global", {}).get("default_max_delay", 10.0),
            ),
            max_retries=request_cfg.get("max_retries", 3),
            timeout=request_cfg.get("timeout", 30),
            respect_robots_txt=self.config.get("global", {}).get(
                "respect_robots_txt", True
            ),
            ssl_legacy=ssl_legacy,
        )

    @abstractmethod
    def collect_product_list(self) -> list[dict[str, Any]]:
        """Collect product list from the institution website.

        Returns a list of raw product dictionaries.
        """
        ...

    @abstractmethod
    def normalize(self, raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize raw items to the unified schema."""
        ...

    def safe_get(self, url: str, **kwargs) -> Any:
        """Convenience wrapper for polite GET."""
        return self.http.get(url, **kwargs)

    def today(self) -> date:
        """Return current date."""
        return date.today()
