"""HTTP client with polite crawling behavior.

Features:
- Per-request randomized delay to avoid hammering target sites
- Configurable retry with exponential backoff
- Consistent but realistic User-Agent and headers
- Optional robots.txt respect
"""

from __future__ import annotations

import random
import ssl
import time
from typing import Any

import requests
import urllib3
from urllib.robotparser import RobotFileParser


class _LegacyRenegotiationAdapter(requests.adapters.HTTPAdapter):
    """Adapter for servers that require unsafe legacy TLS renegotiation."""

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        ctx = urllib3.util.ssl_.create_urllib3_context()
        ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0)
        self.poolmanager = urllib3.PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_context=ctx,
            **pool_kwargs,
        )


class PoliteHttpClient:
    """HTTP client that enforces polite crawling policies."""

    def __init__(
        self,
        user_agent: str | None = None,
        headers: dict[str, str] | None = None,
        min_delay: float = 5.0,
        max_delay: float = 10.0,
        max_retries: int = 3,
        timeout: float = 30.0,
        respect_robots_txt: bool = True,
        ssl_legacy: bool = False,
    ):
        self.user_agent = user_agent or (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
        self.min_delay = max(0.0, float(min_delay))
        self.max_delay = max(self.min_delay, float(max_delay))
        self.max_retries = max(0, int(max_retries))
        self.timeout = float(timeout)
        self.respect_robots_txt = respect_robots_txt
        self._session = requests.Session()
        if ssl_legacy:
            self._session.mount("https://", _LegacyRenegotiationAdapter())
        self._last_request_time: float | None = None
        self._robots_cache: dict[str, RobotFileParser] = {}

        default_headers = {
            "User-Agent": self.user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
        if headers:
            default_headers.update(headers)
        self._session.headers.update(default_headers)

    def _enforce_delay(self) -> None:
        """Sleep a randomized interval since the last request."""
        if self._last_request_time is not None:
            elapsed = time.monotonic() - self._last_request_time
            required = random.uniform(self.min_delay, self.max_delay)
            if elapsed < required:
                time.sleep(required - elapsed)
        self._last_request_time = time.monotonic()

    def _can_fetch(self, url: str) -> bool:
        """Check robots.txt if enabled."""
        if not self.respect_robots_txt:
            return True
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            robots_url = f"{base_url}/robots.txt"

            if base_url not in self._robots_cache:
                rp = RobotFileParser()
                rp.set_url(robots_url)
                rp.read()
                self._robots_cache[base_url] = rp

            return self._robots_cache[base_url].can_fetch(self.user_agent, url)
        except Exception:
            # If robots.txt cannot be parsed, allow fetch conservatively.
            return True

    def get(
        self, url: str, *, params: dict[str, Any] | None = None, **kwargs
    ) -> requests.Response:
        """Perform a polite GET request with retries."""
        if not self._can_fetch(url):
            raise RuntimeError(f"robots.txt disallows fetching {url}")

        kwargs.setdefault("timeout", self.timeout)
        last_exception: Exception | None = None

        for attempt in range(self.max_retries + 1):
            self._enforce_delay()
            try:
                response = self._session.get(url, params=params, **kwargs)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    backoff = 2 ** attempt + random.uniform(0, 1)
                    time.sleep(backoff)
                continue

        raise last_exception or RuntimeError(f"Failed to fetch {url}")

    def post(
        self, url: str, *, data: dict[str, Any] | None = None, **kwargs
    ) -> requests.Response:
        """Perform a polite POST request with retries."""
        kwargs.setdefault("timeout", self.timeout)
        last_exception: Exception | None = None

        for attempt in range(self.max_retries + 1):
            self._enforce_delay()
            try:
                response = self._session.post(url, data=data, **kwargs)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    backoff = 2 ** attempt + random.uniform(0, 1)
                    time.sleep(backoff)
                continue

        raise last_exception or RuntimeError(f"Failed to post {url}")
