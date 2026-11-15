"""The asyncio client: the same transport, parameter, language, retry and error
behaviour as the blocking client."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from datetime import datetime, timezone
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
    ResponseInfo,
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


def test_on_response_client_level_and_per_call() -> None:
    headers = {
        "X-Request-ID": "52a520f261d3db37",
        "X-Credits-Remaining": "64043",
        "X-RateLimit-Limit": "250",
        "X-RateLimit-Remaining": "249",
        "X-RateLimit-Reset": "1794718800",
        "X-Cache": "HIT",
        "Content-Language": "bn",
    }
    rec = Recorder(lambda _r: reply({"ok": 1}, headers=headers))
    seen: list[ResponseInfo] = []
    per_call: list[ResponseInfo] = []

    async def go() -> None:
        client = make_async_client(rec, on_response=seen.append)
        await client.panchang.basic(
            lat=1, lon=2, tz="UTC", lang="bn", request_options={"on_response": per_call.append}
        )

    run(go)
    assert per_call == seen
    assert len(seen) == 1
    info = seen[0]
    assert (info.status, info.path, info.request_id) == (
        200,
        "/v1/panchang/basic",
        "52a520f261d3db37",
    )
    assert (info.credits_remaining, info.cache, info.language) == (64043, "HIT", "bn")
    assert info.rate_limit is not None
    assert (info.rate_limit.limit, info.rate_limit.remaining) == (250, 249)
    assert info.rate_limit.reset_at == datetime.fromtimestamp(1794718800, tz=timezone.utc)


def test_on_response_leaves_out_missing_headers() -> None:
    rec = Recorder(lambda _r: reply({"ok": 1}, headers={"x-request-id": "abc"}))
    seen: list[ResponseInfo] = []
    run(lambda: make_async_client(rec, on_response=seen.append).meta.version())
    assert seen == [ResponseInfo(status=200, path="/v1/meta/version", request_id="abc")]


def test_on_response_reports_the_final_error_once() -> None:
    calls = {"n": 0}

    def unavailable(_r: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return reply({"error": {"code": "x"}}, 503, {"x-request-id": f"r{calls['n']}"})

    seen: list[ResponseInfo] = []
    client = make_async_client(Recorder(unavailable), max_retries=2, on_response=seen.append)
    with pytest.raises(ServerError):
        run(lambda: client.meta.version())
    assert calls["n"] == 3
    assert [(i.status, i.request_id) for i in seen] == [(503, "r3")]


def test_a_raising_on_response_hook_never_breaks_the_call() -> None:
    def broken(_info: ResponseInfo) -> None:
        raise RuntimeError("logger down")

    rec = Recorder(lambda _r: reply({"v": 7}))
    client = make_async_client(rec, on_response=broken)
    assert run(lambda: client.meta.version(request_options={"on_response": broken})) == {"v": 7}
