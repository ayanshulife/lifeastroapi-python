"""The asyncio client: the same transport, parameter, language, retry and error
behaviour as the blocking client."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any, Callable, TypeVar

import httpx
import pytest

from lifeastroapi import (
    AsyncLifeAstro,
    AuthenticationError,
    LifeAstroConnectionError,
    LifeAstroError,
    LifeAstroTimeoutError,
    PaymentRequiredError,
    RateLimitError,
    ServerError,
    __version__,
)

from conftest import BIRTH, GIRL, Recorder, make_async_client, reply

T = TypeVar("T")
NOW: dict[str, Any] = {"lat": 19.076, "lon": 72.8777, "tz": "Asia/Kolkata", "date": "2027-01-15"}


def run(make: Callable[[], Awaitable[T]]) -> T:
    async def main() -> T:
        return await make()

    return asyncio.run(main())


def test_builds_an_authenticated_get_and_unwraps_data() -> None:
    rec = Recorder(lambda _r: reply({"data": {"number": 3}}))

    async def go() -> Any:
        async with make_async_client(rec) as client:
            return await client.panchang.tithi(lat=28.61, lon=77.2, tz="Asia/Kolkata")

    assert run(go) == {"number": 3}
    req = rec.last
    assert req.url.path == "/v1/panchang/tithi"
    assert req.url.params["lat"] == "28.61"
    assert req.headers["Authorization"] == "Bearer dv_live_test"
    assert req.headers["User-Agent"] == f"lifeastroapi-python/{__version__}"


def test_parameter_shapes() -> None:
    rec = Recorder()

    async def go() -> None:
        client = make_async_client(rec)
        await client.chart.planets(**BIRTH)
        await client.milan.mangal_dosha(**BIRTH)
        await client.milan.ashtakoota_total(boy=BIRTH, girl=GIRL)
        await client.western.synastry.aspects(person_a=BIRTH, person_b=GIRL)
        await client.chart.divisional(**BIRTH, varga="D9")
        await client.transit.sade_sati_windows(birth=BIRTH, from_="2027-01-15")
        await client.close()

    run(go)
    assert rec.params(0)["date"] == "1990-01-15"
    assert rec.params(1)["birth.date"] == "1990-01-15"
    assert rec.params(2)["girl.date"] == "1992-03-20"
    assert rec.params(3)["personB.lat"] == "28.6139"
    assert rec.requests[4].url.path == "/v1/chart/divisional/D9"
    assert rec.params(5)["from"] == "2027-01-15"


def test_sends_lang_and_locale() -> None:
    rec = Recorder()

    async def go() -> None:
        client = make_async_client(rec)
        await client.panchang.basic(**NOW, lang="gu")
        await client.chart.planets(**BIRTH, lang="bn")
        await client.horoscope.daily(rashi="Aries", lang="ta")

    run(go)
    assert (rec.params(0)["lang"], rec.params(0)["locale"]) == ("gu", "gu")
    assert (rec.params(1)["lang"], rec.params(1)["locale"]) == ("bn", "bn")
    assert rec.params(2)["lang"] == "ta"
    assert rec.params(2)["rashi"] == "aries"


def test_retries_a_429_then_succeeds() -> None:
    answers = iter(
        [
            reply({"error": {"code": "rate_limited"}}, 429, {"retry-after": "0"}),
            reply({"data": {"ok": True}}),
        ]
    )
    rec = Recorder(lambda _r: next(answers))
    assert run(lambda: make_async_client(rec, max_retries=2).chart.planets(**BIRTH)) == {"ok": True}
    assert len(rec.requests) == 2


def test_gives_up_after_max_retries() -> None:
    rec = Recorder(lambda _r: reply({"error": {"code": "unavailable"}}, 503))
    with pytest.raises(ServerError):
        run(lambda: make_async_client(rec, max_retries=2).chart.planets(**BIRTH))
    assert len(rec.requests) == 3


@pytest.mark.parametrize(
    ("status", "cls"),
    [(401, AuthenticationError), (402, PaymentRequiredError), (429, RateLimitError)],
)
def test_maps_errors(status: int, cls: type[LifeAstroError]) -> None:
    body = {"error": {"code": "c", "message": "m", "request_id": "req_9"}}
    rec = Recorder(lambda _r: reply(body, status, {"retry-after": "5"}))
    with pytest.raises(cls) as info:
        run(lambda: make_async_client(rec).chart.planets(**BIRTH))
    assert (info.value.status, info.value.code, info.value.request_id) == (status, "c", "req_9")
    if isinstance(info.value, RateLimitError):
        assert info.value.retry_after == 5


def test_network_error_and_timeout() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    with pytest.raises(LifeAstroConnectionError) as info:
        run(lambda: make_async_client(Recorder(down)).panchang.tithi(**NOW))
    assert info.value.code == "connection_error"
    with pytest.raises(LifeAstroTimeoutError):
        run(lambda: make_async_client(Recorder(slow)).panchang.tithi(**NOW))


def test_escape_hatch_and_raw() -> None:
    rec = Recorder(lambda _r: reply({"data": {"v": 1}, "meta": {}}))

    async def go() -> tuple[Any, Any]:
        client = make_async_client(rec)
        return await client.get("/v1/anything", {"a": "b"}), await client.request(
            "/v1/anything", request_options={"raw": True}
        )

    plain, raw = run(go)
    assert plain == {"v": 1}
    assert raw == {"data": {"v": 1}, "meta": {}}


def test_context_manager_closes_its_own_client() -> None:
    async def go() -> httpx.AsyncClient:
        async with AsyncLifeAstro(api_key="dv_live_test") as client:
            return client._transport._http

    assert run(go).is_closed


def test_reads_the_api_key_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIFEASTRO_API_KEY", "dv_live_env")
    rec = Recorder()
    client = AsyncLifeAstro(http_client=httpx.AsyncClient(transport=httpx.MockTransport(rec)))
    run(lambda: client.meta.version())
    assert rec.last.headers["Authorization"] == "Bearer dv_live_env"


def test_raises_when_no_api_key_is_provided() -> None:
    with pytest.raises(LifeAstroError, match="API key"):
        AsyncLifeAstro()
