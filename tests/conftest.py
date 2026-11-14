from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lifeastroapi import (  # noqa: E402
    AsyncLifeAstro,
    BirthInput,
    LifeAstro,
    _http,
)

BIRTH: BirthInput = {
    "date": "1990-01-15",
    "time": "10:30",
    "tz": "Asia/Kolkata",
    "lat": 19.076,
    "lon": 72.8777,
}
GIRL: BirthInput = {
    "date": "1992-03-20",
    "time": "08:15",
    "tz": "Asia/Kolkata",
    "lat": 28.6139,
    "lon": 77.209,
}

Reply = Callable[[httpx.Request], httpx.Response]


def reply(
    body: Any = None, status: int = 200, headers: dict[str, str] | None = None
) -> httpx.Response:
    """A canned response; ``body`` is JSON-encoded unless it is a ``str``."""
    if body is None:
        body = {"data": {}}
    content = body.encode() if isinstance(body, str) else json.dumps(body).encode()
    return httpx.Response(
        status,
        content=content,
        headers={"content-type": "application/json", **(headers or {})},
    )


class Recorder:
    """An ``httpx.MockTransport`` handler that records every request."""

    def __init__(self, responder: Reply | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.responder: Reply = responder or (lambda _req: reply({}))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responder(request)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    def params(self, index: int = -1) -> httpx.QueryParams:
        return self.requests[index].url.params


def make_client(rec: Recorder, **kwargs: Any) -> LifeAstro:
    kwargs.setdefault("max_retries", 0)
    kwargs.setdefault("api_key", "dv_live_test")
    return LifeAstro(http_client=httpx.Client(transport=httpx.MockTransport(rec)), **kwargs)


def make_async_client(rec: Recorder, **kwargs: Any) -> AsyncLifeAstro:
    kwargs.setdefault("max_retries", 0)
    kwargs.setdefault("api_key", "dv_live_test")
    return AsyncLifeAstro(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(rec)), **kwargs
    )


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Retries wait 0 s in tests (the real delays are tested on backoff_seconds)."""
    real = _http.backoff_seconds
    monkeypatch.setattr(_http, "backoff_seconds", lambda attempt, retry_after=None: 0.0)
    yield
    monkeypatch.setattr(_http, "backoff_seconds", real)


@pytest.fixture(autouse=True)
def no_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LIFEASTRO_API_KEY", raising=False)
