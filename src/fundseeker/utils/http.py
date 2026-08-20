"""HTTP client with polite crawling behavior.

Features:
- Per-request randomized delay to avoid hammering target sites
- Configurable retry with exponential backoff
- Consistent but realistic User-Agent and headers
- Optional robots.txt respect
"""

from __future__ import annotations

import random
import socket
import ssl
import time
from typing import Any

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib.robotparser import RobotFileParser


class _KeepAliveAdapter(HTTPAdapter):
    """Adapter that enables TCP keepalive to detect dead connections.

    The main failure mode we are targeting is a server that accepts the TCP
    connection but then stops sending data (silent drop). TCP keepalive will
    eventually close such a socket, causing requests to fail fast instead of
    blocking forever. Platform-specific option names are handled gracefully.
    """

    def init_poolmanager(self, *args, **pool_kwargs):
        socket_options = [
            (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
        ]
        # Linux TCP keepalive tunables
        if hasattr(socket, "TCP_KEEPIDLE"):
            socket_options.append((socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30))
        if hasattr(socket, "TCP_KEEPINTVL"):
            socket_options.append((socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10))
        if hasattr(socket, "TCP_KEEPCNT"):
            socket_options.append((socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3))
        # macOS/BSD tunable name
        if hasattr(socket, "TCP_KEEPALIVE"):
            socket_options.append((socket.IPPROTO_TCP, socket.TCP_KEEPALIVE, 30))

        pool_kwargs["socket_options"] = socket_options
        return super().init_poolmanager(*args, **pool_kwargs)


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
        timeout: float | tuple[float, float] = 30.0,
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
        # Normalize timeout to (connect, read) tuple. Keeping read timeout
        # relatively tight prevents a server from silently stalling the
        # response for minutes while still giving it time to send data.
        if isinstance(timeout, (tuple, list)) and len(timeout) >= 2:
            connect_timeout = float(timeout[0])
            read_timeout = float(timeout[1])
        else:
            total = float(timeout)
            connect_timeout = min(10.0, total / 3.0)
            read_timeout = total - connect_timeout
        self.timeout = (connect_timeout, read_timeout)
        self.respect_robots_txt = respect_robots_txt
        self._session = requests.Session()

        # Use a small connection pool and TCP keepalive. A large/default pool
        # can silently reuse a dead connection and block forever on the next
        # request; keepalive plus tight read timeouts makes that far less likely.
        adapter_cls = _LegacyRenegotiationAdapter if ssl_legacy else _KeepAliveAdapter
        adapter = adapter_cls(pool_connections=1, pool_maxsize=2, max_retries=0)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

        self._last_request_time: float | None = None
        self._robots_cache: dict[str, RobotFileParser] = {}
        self._adapter_cls = adapter_cls
        self._headers = headers

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

    def reset_session(self) -> None:
        """Close the current session and create a fresh one.

        Call this after a hard timeout to avoid leaving a hung connection in
        the connection pool for subsequent requests.
        """
        try:
            self._session.close()
        except Exception:
            pass
        self._session = requests.Session()
        adapter = self._adapter_cls(pool_connections=1, pool_maxsize=2, max_retries=0)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

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
        if self._headers:
            default_headers.update(self._headers)
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

    def _request_with_retries(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> requests.Response:
        """Execute a request with polite delay, timeout and retry logic.

        Retry policy:
        * Connect/read timeouts (``requests.Timeout``) — retried with
          exponential backoff + jitter. These typically indicate a flaky
          network or a stalled server and benefit from retry.
        * 5xx and 408/429 (``requests.HTTPError`` for those codes) — retried
          with backoff. These are usually transient.
        * Other 4xx ``requests.HTTPError`` — raised immediately, no retry.
          These are deterministic (404 "not found", 403 "forbidden",
          400 "bad request") and retrying wastes time and rate-limit budget.
        * Other ``RequestException`` (connection errors etc.) — retried.
        """
        kwargs.setdefault("timeout", self.timeout)
        last_exception: Exception | None = None

        # Status codes that are worth retrying even though they are 4xx.
        _RETRYABLE_4XX = {408, 425, 429}

        for attempt in range(self.max_retries + 1):
            # Polite delay only before the first attempt: retries already pay
            # exponential backoff below, so delaying here too would double the
            # wait on every failed request (P2, review 2026-08-20 fs 分析 §2.1).
            if attempt == 0:
                self._enforce_delay()
            try:
                if method == "GET":
                    response = self._session.get(url, **kwargs)
                elif method == "POST":
                    response = self._session.post(url, **kwargs)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                response.raise_for_status()
                return response
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                # Deterministic client error: do not retry.
                if status is not None and 400 <= status < 500 and status not in _RETRYABLE_4XX:
                    raise
                last_exception = exc
                if attempt < self.max_retries:
                    backoff = 2 ** attempt + random.uniform(0, 1)
                    time.sleep(backoff)
                continue
            except requests.Timeout as exc:
                # Timeouts (connect/read) are exactly the failures we expect to
                # see when a server stalls. Always retry them unless this was
                # the last attempt.
                last_exception = exc
                if attempt < self.max_retries:
                    backoff = 2 ** attempt + random.uniform(0, 1)
                    time.sleep(backoff)
                continue
            except requests.RequestException as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    backoff = 2 ** attempt + random.uniform(0, 1)
                    time.sleep(backoff)
                continue

        raise last_exception or RuntimeError(f"Failed to {method} {url}")

    def get(
        self, url: str, *, params: dict[str, Any] | None = None, **kwargs
    ) -> requests.Response:
        """Perform a polite GET request with retries."""
        if not self._can_fetch(url):
            raise RuntimeError(f"robots.txt disallows fetching {url}")
        return self._request_with_retries("GET", url, params=params, **kwargs)

    def post(
        self, url: str, *, data: dict[str, Any] | None = None, **kwargs
    ) -> requests.Response:
        """Perform a polite POST request with retries."""
        return self._request_with_retries("POST", url, data=data, **kwargs)
