"""The small surface a resource group needs from its client."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from .types import QueryValue, RequestOptions


class SyncCore(Protocol):
    def request(
        self,
        path: str,
        query: Mapping[str, QueryValue] | None = None,
        *,
        request_options: RequestOptions | None = None,
    ) -> Any: ...


class AsyncCore(Protocol):
    async def request(
        self,
        path: str,
        query: Mapping[str, QueryValue] | None = None,
        *,
        request_options: RequestOptions | None = None,
    ) -> Any: ...
