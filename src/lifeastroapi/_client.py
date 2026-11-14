"""The LifeAstro clients: configuration, the request method every resource group
uses, and a generic escape hatch (``request`` / ``get``) for any endpoint.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from types import TracebackType
from typing import Any

import httpx

from ._http import AsyncTransport, Config, SyncTransport
from ._version import __version__
from .errors import LifeAstroError
from .resources import AsyncResources, Resources
from .types import QueryValue, RequestOptions

DEFAULT_BASE_URL = "https://api.lifeastroapi.com"
API_KEY_ENV = "LIFEASTRO_API_KEY"


def _resolve_config(
    api_key: str | None,
    base_url: str | None,
    timeout: float,
    max_retries: int,
    default_headers: Mapping[str, str] | None,
) -> Config:
    key = api_key if api_key is not None else os.environ.get(API_KEY_ENV)
    if not key:
        raise LifeAstroError(
            "LifeAstro: an API key is required. Pass api_key=... or set "
            f"{API_KEY_ENV}. Get one at https://lifeastroapi.com/dashboard/keys",
            code="missing_api_key",
            status=0,
        )
    return Config(
        api_key=key,
        base_url=(base_url or DEFAULT_BASE_URL).rstrip("/"),
        timeout=timeout,
        max_retries=max(0, int(max_retries)),
        user_agent=f"lifeastroapi-python/{__version__}",
        default_headers=dict(default_headers or {}),
    )


class LifeAstro(Resources):
    """The LifeAstroAPI client (blocking).

    Args:
        api_key: Your key (``dv_live_...``). Falls back to the
            ``LIFEASTRO_API_KEY`` environment variable.
        base_url: Override the API base URL, e.g. ``http://localhost:8080``.
        timeout: Per-request timeout in seconds. Default 30.
        max_retries: Automatic retries on 429, 5xx and network errors. Default 2.
        default_headers: Extra headers sent on every request.
        http_client: Your own ``httpx.Client`` (proxies, custom transport, tests).
            The SDK does not close a client you pass in.

    Example::

        from lifeastroapi import LifeAstro

        with LifeAstro(api_key="dv_live_...") as client:
            day = client.panchang.basic(lat=19.076, lon=72.8777, tz="Asia/Kolkata")
            chart = client.chart.planets(
                date="1990-01-15", time="10:30", tz="Asia/Kolkata", lat=19.076, lon=72.8777
            )
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 2,
        default_headers: Mapping[str, str] | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        config = _resolve_config(api_key, base_url, timeout, max_retries, default_headers)
        self._transport = SyncTransport(config, http_client)
        super().__init__(self)

    @property
    def base_url(self) -> str:
        """The API base URL this client calls."""
        return self._transport.config.base_url

    def request(
        self,
        path: str,
        query: Mapping[str, QueryValue] | None = None,
        *,
        request_options: RequestOptions | None = None,
    ) -> Any:
        """Call any ``/v1/*`` endpoint directly and return the parsed JSON.

        Useful for an endpoint this SDK version does not wrap yet. ``query``
        uses the API's wire names; ``None`` and ``""`` values are left out::

            client.request("/v1/panchang/tithi", {"lat": 28.61, "lon": 77.2, "tz": "Asia/Kolkata"})
        """
        return self._transport.request(path, query, request_options)

    def get(
        self,
        path: str,
        query: Mapping[str, QueryValue] | None = None,
        *,
        request_options: RequestOptions | None = None,
    ) -> Any:
        """Alias for :meth:`request`."""
        return self.request(path, query, request_options=request_options)

    def close(self) -> None:
        """Close the underlying HTTP client (unless you passed your own)."""
        self._transport.close()

    def __enter__(self) -> LifeAstro:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class AsyncLifeAstro(AsyncResources):
    """The LifeAstroAPI client for ``asyncio``. Same methods as :class:`LifeAstro`,
    each one a coroutine.

    Args:
        api_key: Your key (``dv_live_...``). Falls back to the
            ``LIFEASTRO_API_KEY`` environment variable.
        base_url: Override the API base URL, e.g. ``http://localhost:8080``.
        timeout: Per-request timeout in seconds. Default 30.
        max_retries: Automatic retries on 429, 5xx and network errors. Default 2.
        default_headers: Extra headers sent on every request.
        http_client: Your own ``httpx.AsyncClient``. The SDK does not close a
            client you pass in.

    Example::

        import asyncio
        from lifeastroapi import AsyncLifeAstro

        async def main() -> None:
            async with AsyncLifeAstro() as client:
                day = await client.panchang.basic(lat=23.0225, lon=72.5714, tz="Asia/Kolkata")

        asyncio.run(main())
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 2,
        default_headers: Mapping[str, str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        config = _resolve_config(api_key, base_url, timeout, max_retries, default_headers)
        self._transport = AsyncTransport(config, http_client)
        super().__init__(self)

    @property
    def base_url(self) -> str:
        """The API base URL this client calls."""
        return self._transport.config.base_url

    async def request(
        self,
        path: str,
        query: Mapping[str, QueryValue] | None = None,
        *,
        request_options: RequestOptions | None = None,
    ) -> Any:
        """Call any ``/v1/*`` endpoint directly and return the parsed JSON."""
        return await self._transport.request(path, query, request_options)

    async def get(
        self,
        path: str,
        query: Mapping[str, QueryValue] | None = None,
        *,
        request_options: RequestOptions | None = None,
    ) -> Any:
        """Alias for :meth:`request`."""
        return await self.request(path, query, request_options=request_options)

    async def close(self) -> None:
        """Close the underlying HTTP client (unless you passed your own)."""
        await self._transport.close()

    aclose = close

    async def __aenter__(self) -> AsyncLifeAstro:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()
