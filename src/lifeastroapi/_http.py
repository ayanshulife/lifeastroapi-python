"""HTTP transport: URL and query building, bearer auth, timeout, envelope
unwrapping, typed errors, and bounded retries with exponential backoff that
honour ``Retry-After``. Same behaviour as the Node SDK's ``src/http.ts``.
"""

from __future__ import annotations

import asyncio
import json
import math
import random
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from ._params import _text
from .errors import (
    LifeAstroConnectionError,
    LifeAstroError,
    LifeAstroTimeoutError,
    error_from_response,
)
from .types import QueryValue, RequestOptions

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class Config:
    """Resolved client configuration."""

    api_key: str = field(repr=False)
    base_url: str
    timeout: float
    max_retries: int
    user_agent: str
    default_headers: Mapping[str, str]


def encode_query(params: Mapping[str, QueryValue] | None) -> str:
    """Encode params into a sorted query string, leaving out ``None`` and ``""``."""
    if not params:
        return ""
    pairs = []
    for key in sorted(params):
        value = params[key]
        if value is None or value == "":
            continue
        pairs.append((key, _text(value)))
    return "?" + urlencode(pairs) if pairs else ""


def build_url(config: Config, path: str, query: Mapping[str, QueryValue] | None) -> str:
    return config.base_url + (path if path.startswith("/") else "/" + path) + encode_query(query)


def build_headers(config: Config) -> dict[str, str]:
    """Bearer token (header only, never in the URL), JSON accept, User-Agent.

    ``default_headers`` are applied last, so a caller can override any of them.
    """
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Accept": "application/json",
        "User-Agent": config.user_agent,
    }
    headers.update(config.default_headers)
    return headers


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """Seconds from a ``Retry-After`` header: delta-seconds or an HTTP date."""
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        pass
    else:
        return max(0.0, seconds) if math.isfinite(seconds) else None
    try:
        at = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if at is None:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    current = now if now is not None else datetime.now(timezone.utc)
    return max(0.0, (at - current).total_seconds())


def backoff_seconds(attempt: int, retry_after: float | None = None) -> float:
    """Wait before retry ``attempt`` (0-based): ``Retry-After`` capped at 30 s,
    else 0.5 s doubling up to 8 s, plus up to 0.25 s of jitter."""
    if retry_after is not None:
        return min(retry_after, 30.0)
    return min(0.5 * 2.0**attempt, 8.0) + random.uniform(0, 0.25)


def _parse_body(content: bytes) -> Any:
    if not content:
        return None
    try:
        return json.loads(content)
    except ValueError:
        return content.decode("utf-8", errors="replace")


def _success(body: Any, raw: bool) -> Any:
    # The API returns bare JSON today. A {data, meta} envelope is unwrapped if a
    # response ever carries one, so adding it server-side is not a breaking change.
    if not raw and isinstance(body, dict) and "data" in body:
        return body["data"]
    return body


def _transport_error(exc: httpx.RequestError, timeout: float) -> LifeAstroConnectionError:
    err: LifeAstroConnectionError
    if isinstance(exc, httpx.TimeoutException):
        err = LifeAstroTimeoutError(f"Request timed out after {timeout:g}s")
    else:
        err = LifeAstroConnectionError(f"Network request failed: {exc}")
    err.__cause__ = exc
    return err


def _retryable(err: LifeAstroError) -> bool:
    return err.status == 0 or err.status in RETRYABLE_STATUS


class SyncTransport:
    """Blocking transport on ``httpx.Client``."""

    def __init__(self, config: Config, http_client: httpx.Client | None) -> None:
        self.config = config
        self._owns_client = http_client is None
        self._http = http_client if http_client is not None else httpx.Client()

    def request(
        self,
        path: str,
        query: Mapping[str, QueryValue] | None,
        options: RequestOptions | None = None,
    ) -> Any:
        opts: RequestOptions = options or {}
        url = build_url(self.config, path, query)
        timeout = opts.get("timeout", self.config.timeout)
        headers = build_headers(self.config)
        attempt = 0
        while True:
            retry_after: float | None = None
            try:
                response = self._http.request("GET", url, headers=headers, timeout=timeout)
            except httpx.RequestError as exc:
                err: LifeAstroError = _transport_error(exc, timeout)
            else:
                body = _parse_body(response.content)
                if 200 <= response.status_code < 300:
                    return _success(body, opts.get("raw", False))
                retry_after = parse_retry_after(response.headers.get("retry-after"))
                err = error_from_response(response.status_code, body, retry_after)
            if attempt >= self.config.max_retries or not _retryable(err):
                raise err
            time.sleep(backoff_seconds(attempt, retry_after))
            attempt += 1

    def close(self) -> None:
        if self._owns_client:
            self._http.close()


class AsyncTransport:
    """Non-blocking transport on ``httpx.AsyncClient``."""

    def __init__(self, config: Config, http_client: httpx.AsyncClient | None) -> None:
        self.config = config
        self._owns_client = http_client is None
        self._http = http_client if http_client is not None else httpx.AsyncClient()

    async def request(
        self,
        path: str,
        query: Mapping[str, QueryValue] | None,
        options: RequestOptions | None = None,
    ) -> Any:
        opts: RequestOptions = options or {}
        url = build_url(self.config, path, query)
        timeout = opts.get("timeout", self.config.timeout)
        headers = build_headers(self.config)
        attempt = 0
        while True:
            retry_after: float | None = None
            try:
                response = await self._http.request("GET", url, headers=headers, timeout=timeout)
            except httpx.RequestError as exc:
                err: LifeAstroError = _transport_error(exc, timeout)
            else:
                body = _parse_body(response.content)
                if 200 <= response.status_code < 300:
                    return _success(body, opts.get("raw", False))
                retry_after = parse_retry_after(response.headers.get("retry-after"))
                err = error_from_response(response.status_code, body, retry_after)
            if attempt >= self.config.max_retries or not _retryable(err):
                raise err
            await asyncio.sleep(backoff_seconds(attempt, retry_after))
            attempt += 1

    async def close(self) -> None:
        if self._owns_client:
            await self._http.aclose()
