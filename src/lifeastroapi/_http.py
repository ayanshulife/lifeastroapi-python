"""HTTP transport: URL and query building, bearer auth, timeout, envelope
unwrapping, typed errors, bounded retries with exponential backoff that
honour ``Retry-After``, and the ``on_response`` hook. Same behaviour as the Node
SDK's ``src/http.ts``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import random
import re
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
    non_json_error,
)
from .types import QueryValue, RateLimit, RequestOptions, ResponseHook, ResponseInfo

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
    on_response: ResponseHook | None = None


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


def _normalize_path(path: str) -> str:
    return path if path.startswith("/") else "/" + path


def build_url(config: Config, path: str, query: Mapping[str, QueryValue] | None) -> str:
    return config.base_url + _normalize_path(path) + encode_query(query)


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


def _header_int(headers: httpx.Headers, name: str) -> int | None:
    value = headers.get(name)
    if value is None:
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


def response_info(response: httpx.Response, path: str) -> ResponseInfo:
    """Read the :class:`ResponseInfo` of a response. Header names are case-insensitive;
    a header that is missing or not a number leaves its field ``None``."""
    headers = response.headers
    rate_limit: RateLimit | None = None
    limit = _header_int(headers, "x-ratelimit-limit")
    remaining = _header_int(headers, "x-ratelimit-remaining")
    reset = _header_int(headers, "x-ratelimit-reset")
    if limit is not None and remaining is not None and reset is not None:
        with contextlib.suppress(OverflowError, OSError, ValueError):
            rate_limit = RateLimit(
                limit=limit,
                remaining=remaining,
                reset_at=datetime.fromtimestamp(reset, tz=timezone.utc),
            )
    return ResponseInfo(
        status=response.status_code,
        path=_normalize_path(path),
        request_id=headers.get("x-request-id") or None,
        credits_remaining=_header_int(headers, "x-credits-remaining"),
        rate_limit=rate_limit,
        cache=headers.get("x-cache") or None,
        language=headers.get("content-language") or None,
    )


def _emit(config: Config, opts: RequestOptions, response: httpx.Response, path: str) -> None:
    """Call the client-level hook, then the per-call one. A hook that raises never
    breaks the call."""
    hooks = [hook for hook in (config.on_response, opts.get("on_response")) if hook is not None]
    if not hooks:
        return
    info = response_info(response, path)
    for hook in hooks:
        with contextlib.suppress(Exception):
            hook(info)


def _parse_body(content: bytes) -> tuple[Any, bool]:
    """The parsed body, and whether it was not JSON (then the body is its text)."""
    if not content:
        return None, False
    try:
        return json.loads(content), False
    except ValueError:
        return content.decode("utf-8", errors="replace"), True


def _success(body: Any, raw: bool) -> Any:
    # The API returns bare JSON today. A {data, meta} envelope is unwrapped if a
    # response ever carries one, so adding it server-side is not a breaking change.
    if not raw and isinstance(body, dict) and "data" in body:
        return body["data"]
    return body


_BEARER = re.compile(r"(Bearer\s+)[^\s'\"]+")


def _transport_error(
    exc: httpx.RequestError, timeout: float, api_key: str = ""
) -> LifeAstroConnectionError:
    err: LifeAstroConnectionError
    if isinstance(exc, httpx.TimeoutException):
        err = LifeAstroTimeoutError(f"Request timed out after {timeout:g}s")
    else:
        # httpx quotes a header value it rejects: never let the key into the message.
        detail = str(exc)
        if api_key:
            detail = detail.replace(api_key, "***")
        detail = _BEARER.sub(r"\1***", detail)
        err = LifeAstroConnectionError(f"Network request failed: {detail}")
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
            answered: httpx.Response | None = None  # an HTTP response, not a network failure
            try:
                response = self._http.request("GET", url, headers=headers, timeout=timeout)
            except httpx.RequestError as exc:
                err: LifeAstroError = _transport_error(exc, timeout, self.config.api_key)
            else:
                body, non_json = _parse_body(response.content)
                if 200 <= response.status_code < 300:
                    _emit(self.config, opts, response, path)
                    if non_json:
                        # A 2xx that is not JSON is not an API answer (a proxy or captive page).
                        raise non_json_error(response.status_code, body)
                    return _success(body, opts.get("raw", False))
                answered = response
                retry_after = parse_retry_after(response.headers.get("retry-after"))
                if non_json:
                    err = non_json_error(response.status_code, body, retry_after)
                else:
                    err = error_from_response(response.status_code, body, retry_after)
            if attempt >= self.config.max_retries or not _retryable(err):
                if answered is not None:
                    _emit(self.config, opts, answered, path)
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
            answered: httpx.Response | None = None  # an HTTP response, not a network failure
            try:
                response = await self._http.request("GET", url, headers=headers, timeout=timeout)
            except httpx.RequestError as exc:
                err: LifeAstroError = _transport_error(exc, timeout, self.config.api_key)
            else:
                body, non_json = _parse_body(response.content)
                if 200 <= response.status_code < 300:
                    _emit(self.config, opts, response, path)
                    if non_json:
                        # A 2xx that is not JSON is not an API answer (a proxy or captive page).
                        raise non_json_error(response.status_code, body)
                    return _success(body, opts.get("raw", False))
                answered = response
                retry_after = parse_retry_after(response.headers.get("retry-after"))
                if non_json:
                    err = non_json_error(response.status_code, body, retry_after)
                else:
                    err = error_from_response(response.status_code, body, retry_after)
            if attempt >= self.config.max_retries or not _retryable(err):
                if answered is not None:
                    _emit(self.config, opts, answered, path)
                raise err
            await asyncio.sleep(backoff_seconds(attempt, retry_after))
            attempt += 1

    async def close(self) -> None:
        if self._owns_client:
            await self._http.aclose()
