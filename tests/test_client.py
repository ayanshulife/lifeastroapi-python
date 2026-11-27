"""The blocking client. Same cases as the Node SDK's test/client.test.ts."""

from __future__ import annotations

import inspect
import re
from datetime import datetime, timezone
from typing import Any, Callable

import httpx
import pytest

from lifeastroapi import (
    LOCALES,
    AuthenticationError,
    BadRequestError,
    LifeAstro,
    LifeAstroConnectionError,
    LifeAstroError,
    LifeAstroTimeoutError,
    NotFoundError,
    PaymentRequiredError,
    PermissionDeniedError,
    RateLimit,
    RateLimitError,
    ResponseInfo,
    ServerError,
    __version__,
)
from lifeastroapi._http import backoff_seconds, encode_query, parse_retry_after
from lifeastroapi._params import today_in

from conftest import BIRTH, GIRL, Recorder, make_client, reply

NOW: dict[str, Any] = {"lat": 19.076, "lon": 72.8777, "tz": "Asia/Kolkata", "date": "2027-01-15"}


# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------
def test_builds_an_authenticated_get_and_unwraps_data() -> None:
    rec = Recorder(lambda _r: reply({"data": {"number": 3}, "meta": {"cache": "miss"}}))
    res = make_client(rec).panchang.tithi(lat=28.61, lon=77.2, tz="Asia/Kolkata")

    assert res == {"number": 3}
    req = rec.last
    assert req.method == "GET"
    assert req.url.scheme == "https"
    assert req.url.host == "api.lifeastroapi.com"
    assert req.url.path == "/v1/panchang/tithi"
    assert req.url.params["lat"] == "28.61"
    assert req.url.params["tz"] == "Asia/Kolkata"
    assert req.headers["Authorization"] == "Bearer dv_live_test"
    assert req.headers["Accept"] == "application/json"
    assert req.headers["User-Agent"] == f"lifeastroapi-python/{__version__}"


def test_returns_the_bare_json_body() -> None:
    body = {"index": 6, "name": "Saptami", "paksha": "Shukla"}
    rec = Recorder(lambda _r: reply(body))
    assert make_client(rec).panchang.tithi(**NOW) == body


def test_returns_the_full_envelope_with_raw() -> None:
    rec = Recorder(lambda _r: reply({"data": {"x": 1}, "meta": {"tier": "standard"}}))
    res = make_client(rec).request(
        "/v1/panchang/tithi", {"lat": 1, "lon": 2, "tz": "UTC"}, request_options={"raw": True}
    )
    assert res == {"data": {"x": 1}, "meta": {"tier": "standard"}}


def test_omits_empty_params_and_sorts_the_query_string() -> None:
    rec = Recorder()
    make_client(rec).panchang.tithi(lat=28.61, lon=77.2, tz="Asia/Kolkata", date="")
    assert "date" not in rec.params()
    keys = [k for k, _ in rec.params().multi_items()]
    assert keys == sorted(keys)


def test_per_call_timeout_reaches_httpx() -> None:
    rec = Recorder()
    client = make_client(rec, timeout=12.5)
    client.panchang.tithi(**NOW)
    client.panchang.tithi(**NOW, request_options={"timeout": 3})
    assert rec.requests[0].extensions["timeout"]["read"] == 12.5
    assert rec.requests[1].extensions["timeout"]["read"] == 3


# ---------------------------------------------------------------------------
# parameter shapes
# ---------------------------------------------------------------------------
def test_flat_birth_params() -> None:
    rec = Recorder()
    make_client(rec).chart.planets(**BIRTH)
    q = rec.params()
    assert q["date"] == "1990-01-15"
    assert q["time"] == "10:30"
    assert q["lat"] == "19.076"
    assert "birth.date" not in q


def test_birth_prefixed_params() -> None:
    rec = Recorder()
    make_client(rec).milan.mangal_dosha(**BIRTH)
    assert rec.last.url.path == "/v1/milan/mangal-dosha"
    q = rec.params()
    assert q["birth.date"] == "1990-01-15"
    assert q["birth.lat"] == "19.076"
    assert "date" not in q


def test_boy_girl_matchmaking_params() -> None:
    rec = Recorder()
    make_client(rec).milan.ashtakoota_total(boy=BIRTH, girl={**BIRTH, "date": "1992-03-20"})
    q = rec.params()
    assert q["boy.date"] == "1990-01-15"
    assert q["girl.date"] == "1992-03-20"
    assert q["girl.lon"] == "72.8777"


def test_western_pairs_use_person_a_and_person_b() -> None:
    rec = Recorder()
    make_client(rec).western.synastry.aspects(person_a=BIRTH, person_b=GIRL)
    q = rec.params()
    assert q["personA.date"] == "1990-01-15"
    assert q["personB.date"] == "1992-03-20"
    assert q["personB.lat"] == "28.6139"


def test_lowercases_rashi() -> None:
    rec = Recorder()
    make_client(rec).horoscope.daily(rashi="Aries")
    assert rec.params()["rashi"] == "aries"


def test_substitutes_path_params() -> None:
    rec = Recorder()
    make_client(rec).chart.divisional(**BIRTH, varga="D9")
    assert rec.last.url.path == "/v1/chart/divisional/D9"
    assert "varga" not in rec.params()


def test_custom_shape_festivals_month() -> None:
    rec = Recorder()
    make_client(rec).festivals.month(
        year=2026,
        month=11,
        tz="Asia/Kolkata",
        lat=19.076,
        lon=72.8777,
        locale="mr",
        month_system="amanta",
    )
    q = rec.params()
    assert q["year"] == "2026"
    assert q["lat"] == "19.076"
    assert q["month_system"] == "amanta"
    assert q["locale"] == "mr"


def test_natal_transit_maps_natal_to_birth_and_transit_flat() -> None:
    rec = Recorder()
    make_client(rec).western.transits.to_natal(
        birth=BIRTH, date="2026-06-16", time="12:00", tz="Asia/Kolkata"
    )
    q = rec.params()
    assert q["birth.date"] == "1990-01-15"
    assert q["date"] == "2026-06-16"


def test_exposes_nested_western_groups() -> None:
    client = make_client(Recorder())
    assert callable(client.western.natal.chart)
    assert callable(client.western.synastry.aspects)
    assert callable(client.western.solar_arc.aspects_to_natal)
    assert callable(client.western.firdaria)


def test_raises_on_an_empty_path_parameter() -> None:
    client = make_client(Recorder())
    with pytest.raises(ValueError, match="path parameter"):
        client.chart.divisional(**BIRTH, varga="")


def test_keyword_only_arguments() -> None:
    client = make_client(Recorder())
    with pytest.raises(TypeError):
        client.chart.divisional("D9", **BIRTH)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------
def _failing(status: int, body: Any, headers: dict[str, str] | None = None) -> LifeAstro:
    return make_client(Recorder(lambda _r: reply(body, status, headers)))


def test_maps_401_to_authentication_error() -> None:
    client = _failing(
        401, {"error": {"code": "unauthorized", "message": "bad key", "request_id": "req_1"}}
    )
    with pytest.raises(AuthenticationError) as info:
        client.chart.planets(**BIRTH)
    err = info.value
    assert isinstance(err, LifeAstroError)
    assert (err.code, err.status, err.request_id, err.message) == (
        "unauthorized",
        401,
        "req_1",
        "bad key",
    )
    assert str(err) == "bad key (HTTP 401, code=unauthorized, request_id=req_1)"


@pytest.mark.parametrize(
    ("status", "cls"),
    [
        (400, BadRequestError),
        (402, PaymentRequiredError),
        (403, PermissionDeniedError),
        (404, NotFoundError),
        (429, RateLimitError),
        (500, ServerError),
        (503, ServerError),
    ],
)
def test_maps_status_to_error_class(status: int, cls: type[LifeAstroError]) -> None:
    client = _failing(status, {"error": {"code": "x", "message": "m"}})
    with pytest.raises(cls) as info:
        client.chart.planets(**BIRTH)
    assert info.value.status == status
    assert info.value.code == "x"


def test_unknown_4xx_is_the_base_error_with_a_default_code() -> None:
    client = _failing(418, {"teapot": True})
    with pytest.raises(LifeAstroError) as info:
        client.chart.planets(**BIRTH)
    assert type(info.value) is LifeAstroError
    assert info.value.code == "bad_request"
    assert info.value.message == "HTTP 418"
    assert info.value.body == {"teapot": True}


def test_html_error_page_is_non_json_response_with_the_class_of_its_status() -> None:
    client = _failing(403, "<html><body>Access denied</body></html>")
    with pytest.raises(PermissionDeniedError) as info:
        client.chart.planets(**BIRTH)
    assert info.value.code == "non_json_response"
    assert "HTTP 403" in info.value.message
    assert "<html><body>Access denied" in info.value.message


def test_non_json_success_body_raises_non_json_response() -> None:
    client = _failing(200, "plain text")
    with pytest.raises(LifeAstroError) as info:
        client.request("/v1/text")
    assert info.value.code == "non_json_response"
    assert info.value.status == 200


def test_maps_429_with_retry_after() -> None:
    client = _failing(
        429, {"error": {"code": "rate_limited", "message": "slow down"}}, {"retry-after": "7"}
    )
    with pytest.raises(RateLimitError) as info:
        client.chart.planets(**BIRTH)
    assert info.value.retry_after == 7


def test_parses_the_http_date_form_of_retry_after() -> None:
    client = _failing(
        429, {"error": {"code": "rate_limited"}}, {"retry-after": "Wed, 21 Oct 2099 07:28:00 GMT"}
    )
    with pytest.raises(RateLimitError) as info:
        client.chart.planets(**BIRTH)
    assert info.value.retry_after is not None and info.value.retry_after > 0


def test_parse_retry_after() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert parse_retry_after("3", now) == 3
    assert parse_retry_after("-4", now) == 0
    assert parse_retry_after("Thu, 01 Jan 2026 00:00:10 GMT", now) == 10
    assert parse_retry_after("soon", now) is None
    assert parse_retry_after(None, now) is None


def test_backoff_doubles_with_jitter_and_caps() -> None:
    assert 0.5 <= backoff_seconds(0) <= 0.75
    assert 1.0 <= backoff_seconds(1) <= 1.25
    assert 8.0 <= backoff_seconds(10) <= 8.25
    assert backoff_seconds(0, 7) == 7
    assert backoff_seconds(0, 120) == 30


# ---------------------------------------------------------------------------
# retries
# ---------------------------------------------------------------------------
def test_retries_a_429_then_succeeds() -> None:
    answers = iter(
        [
            reply({"error": {"code": "rate_limited"}}, 429, {"retry-after": "0"}),
            reply({"data": {"ok": True}}),
        ]
    )
    rec = Recorder(lambda _r: next(answers))
    assert make_client(rec, max_retries=2).chart.planets(**BIRTH) == {"ok": True}
    assert len(rec.requests) == 2


def test_gives_up_after_max_retries() -> None:
    rec = Recorder(lambda _r: reply({"error": {"code": "unavailable"}}, 503, {"retry-after": "0"}))
    with pytest.raises(ServerError) as info:
        make_client(rec, max_retries=2).chart.planets(**BIRTH)
    assert info.value.status == 503
    assert len(rec.requests) == 3  # first try + 2 retries


def test_clamps_a_negative_max_retries_to_zero() -> None:
    rec = Recorder(lambda _r: reply({"error": {"code": "unavailable"}}, 503))
    with pytest.raises(ServerError):
        make_client(rec, max_retries=-5).chart.planets(**BIRTH)
    assert len(rec.requests) == 1


def test_does_not_retry_a_non_retryable_4xx() -> None:
    rec = Recorder(lambda _r: reply({"error": {"code": "invalid_param"}}, 400))
    with pytest.raises(BadRequestError):
        make_client(rec, max_retries=3).chart.planets(**BIRTH)
    assert len(rec.requests) == 1


def test_retries_a_network_error_then_succeeds() -> None:
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("ECONNRESET", request=request)
        return reply({"data": {"ok": True}})

    assert make_client(Recorder(flaky), max_retries=2).chart.planets(**BIRTH) == {"ok": True}
    assert calls["n"] == 2


def test_network_failure_is_a_connection_error() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(LifeAstroConnectionError) as info:
        make_client(Recorder(down), max_retries=1).panchang.tithi(**NOW)
    assert info.value.status == 0
    assert info.value.code == "connection_error"
    assert isinstance(info.value.__cause__, httpx.ConnectError)


def test_timeout_is_a_timeout_error() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    rec = Recorder(slow)
    with pytest.raises(LifeAstroTimeoutError) as info:
        make_client(rec, max_retries=1).panchang.tithi(**NOW, request_options={"timeout": 0.01})
    assert info.value.code == "timeout"
    assert isinstance(info.value, LifeAstroConnectionError)
    assert len(rec.requests) == 2  # timeouts are retried like network errors


# ---------------------------------------------------------------------------
# languages
# ---------------------------------------------------------------------------
def test_sends_both_lang_and_locale() -> None:
    rec = Recorder()
    make_client(rec).narrative.lagna(**BIRTH, lang="hi")
    assert rec.params()["lang"] == "hi"
    assert rec.params()["locale"] == "hi"


# One method per Vedic group; `both` is False where the shape itself sends `lang` only.
VEDIC: list[tuple[str, str, Callable[[LifeAstro], Any], bool]] = [
    ("panchang.basic", "/v1/panchang/basic", lambda c: c.panchang.basic(**NOW, lang="gu"), True),
    ("panchang.panchaka", "/v1/panchang/panchaka", lambda c: c.panchang.panchaka(**NOW, lang="gu"), True),
    ("calendar.ritu", "/v1/calendar/ritu", lambda c: c.calendar.ritu(date=NOW["date"], tz=NOW["tz"], lang="gu"), True),
    ("festivals.month", "/v1/festivals/month", lambda c: c.festivals.month(year=2027, month=1, lang="gu"), True),
    ("eclipses.all", "/v1/eclipses/all", lambda c: c.eclipses.all(start_date="2027-01-01", end_date="2027-12-31", lang="gu"), True),
    ("planet_moments.ingress", "/v1/planet-moments/ingress", lambda c: c.planet_moments.ingress(planet="Jupiter", date=NOW["date"], tz=NOW["tz"], lang="gu"), True),
    ("transit.positions", "/v1/transit/positions", lambda c: c.transit.positions(lang="gu"), True),
    ("transit.tarabala", "/v1/transit/tarabala", lambda c: c.transit.tarabala(birth=BIRTH, date=NOW["date"], time="06:00", tz=NOW["tz"], lang="gu"), True),
    ("milan.ashtakoota", "/v1/milan/ashtakoota", lambda c: c.milan.ashtakoota(boy=BIRTH, girl=GIRL, lang="gu"), True),
    ("muhurta.vivah", "/v1/muhurta/vivah", lambda c: c.muhurta.vivah(**NOW, lang="gu"), True),
    ("muhurta.best_time", "/v1/muhurta/best-time", lambda c: c.muhurta.best_time(lat=NOW["lat"], lon=NOW["lon"], tz=NOW["tz"], start_date="2027-01-15", end_date="2027-01-17", lang="gu"), True),
    ("chart.planets", "/v1/chart/planets", lambda c: c.chart.planets(**BIRTH, lang="gu"), True),
    ("chart.kundli_facts", "/v1/chart/kundli-facts", lambda c: c.chart.kundli_facts(**BIRTH, lang="gu"), True),
    ("prashna.chart", "/v1/prashna/chart", lambda c: c.prashna.chart(**NOW, time="12:00", lang="gu"), True),
    ("numerology.driver", "/v1/numerology/driver", lambda c: c.numerology.driver(dob="1990-01-15", lang="gu"), True),
    ("numerology.full", "/v1/numerology/full", lambda c: c.numerology.full(name="Arjun Mehta", dob="1990-01-15", lang="gu"), False),
    ("dasha.vimshottari", "/v1/dasha/vimshottari", lambda c: c.dasha.vimshottari(**BIRTH, lang="gu"), True),
    ("varshaphal.chart", "/v1/varshaphal/chart", lambda c: c.varshaphal.chart(**BIRTH, year=2026, lang="gu"), True),
    ("ashtakavarga.bhinna", "/v1/ashtakavarga/bhinna/Jupiter", lambda c: c.ashtakavarga.bhinna(**BIRTH, planet="Jupiter", lang="gu"), True),
    ("lalkitab.chart", "/v1/lalkitab/chart", lambda c: c.lalkitab.chart(**BIRTH, lang="gu"), True),
    ("horoscope.daily", "/v1/horoscope/daily", lambda c: c.horoscope.daily(rashi="aries", lang="gu"), False),
    ("reports.kundli_lite", "/v1/reports/kundli/lite", lambda c: c.reports.kundli_lite(**BIRTH, lang="gu"), True),
    ("narrative.yearly_bhavishyafal", "/v1/vedic/narrative/yearly-bhavishyafal", lambda c: c.narrative.yearly_bhavishyafal(**BIRTH, year=2027, lang="gu"), True),
    ("remedies.for_graha", "/v1/vedic/remedies/for-graha", lambda c: c.remedies.for_graha(graha="saturn", lang="gu"), True),
]  # fmt: skip


@pytest.mark.parametrize(("name", "path", "call", "both"), VEDIC, ids=[v[0] for v in VEDIC])
def test_vedic_group_sends_the_language(
    name: str, path: str, call: Callable[[LifeAstro], Any], both: bool
) -> None:
    rec = Recorder()
    call(make_client(rec))
    assert rec.last.url.path == path
    assert rec.params()["lang"] == "gu"
    if both:
        assert rec.params()["locale"] == "gu"


def test_accepts_every_locale_including_pa() -> None:
    rec = Recorder()
    client = make_client(rec)
    for lang in LOCALES:
        client.panchang.tithi(**NOW, lang=lang)
    assert [r.url.params["locale"] for r in rec.requests] == list(LOCALES)
    assert len(LOCALES) == 10


def test_sends_no_language_when_lang_is_omitted() -> None:
    rec = Recorder()
    make_client(rec).panchang.basic(**NOW)
    assert "lang" not in rec.params()
    assert "locale" not in rec.params()


def test_locale_input_still_works_and_lang_wins() -> None:
    rec = Recorder()
    client = make_client(rec)
    client.festivals.month(year=2027, month=1, locale="hi")
    client.panchang.monthly(
        lat=NOW["lat"], lon=NOW["lon"], year=2027, month=1, locale="hi", lang="gu"
    )
    assert rec.params(0)["locale"] == "hi"
    assert "lang" not in rec.params(0)
    assert rec.params(1)["locale"] == "gu"
    assert rec.params(1)["lang"] == "gu"


# English-only products and Vedic endpoints with nothing to translate take no `lang`.
NO_LANG: list[Callable[[LifeAstro], Any]] = [
    lambda c: c.western.natal.planets,
    lambda c: c.western.synastry.aspects,
    lambda c: c.western.transits.positions,
    lambda c: c.tarot.daily,
    lambda c: c.geo.search,
    lambda c: c.meta.version,
    lambda c: c.panchang.rahu_kaal,
    lambda c: c.chart.yogas,
    lambda c: c.transit.windows,
]


@pytest.mark.parametrize("method", NO_LANG)
def test_methods_without_lang(method: Callable[[LifeAstro], Any]) -> None:
    fn = method(make_client(Recorder()))
    assert "lang" not in inspect.signature(fn).parameters
    with pytest.raises(TypeError):
        fn(lang="gu")


def test_western_narrative_keeps_its_own_lang() -> None:
    rec = Recorder()
    make_client(rec).western.narrative.sabian(degree=100, lang="hi")
    assert rec.params()["lang"] == "hi"


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------
def test_raises_when_no_api_key_is_provided() -> None:
    with pytest.raises(LifeAstroError, match="API key") as info:
        LifeAstro()
    assert info.value.code == "missing_api_key"


def test_trims_the_api_key_and_rejects_a_blank_one() -> None:
    rec = Recorder()
    make_client(rec, api_key=" dv_live_test\n").request("/v1/x")
    assert rec.last.headers["Authorization"] == "Bearer dv_live_test"
    with pytest.raises(LifeAstroError) as info:
        LifeAstro(api_key=" \n")
    assert info.value.code == "missing_api_key"


def test_a_transport_error_never_carries_the_key() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.LocalProtocolError(
            f"Illegal header value {request.headers['Authorization']!r}", request=request
        )

    client = make_client(Recorder(fail), api_key="dv_live_se cret")
    with pytest.raises(LifeAstroConnectionError) as info:
        client.request("/v1/x")
    assert "cret" not in str(info.value)
    assert "dv_live_se" not in str(info.value)


def test_reads_the_api_key_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIFEASTRO_API_KEY", "dv_live_env")
    rec = Recorder()
    client = LifeAstro(http_client=httpx.Client(transport=httpx.MockTransport(rec)))
    client.panchang.tithi(lat=1, lon=2, tz="UTC")
    assert rec.last.headers["Authorization"] == "Bearer dv_live_env"


def test_accepts_the_key_as_the_first_argument() -> None:
    rec = Recorder()
    client = LifeAstro("dv_live_str", http_client=httpx.Client(transport=httpx.MockTransport(rec)))
    client.meta.version()
    assert rec.last.headers["Authorization"] == "Bearer dv_live_str"


def test_custom_base_url_and_default_headers() -> None:
    rec = Recorder()
    client = make_client(
        rec,
        base_url="http://127.0.0.1:18080/",
        default_headers={"X-Trace": "abc", "Authorization": "Bearer other"},
    )
    client.panchang.tithi(lat=1, lon=2, tz="UTC")
    assert client.base_url == "http://127.0.0.1:18080"
    assert str(rec.last.url).startswith("http://127.0.0.1:18080/v1/panchang/tithi?")
    assert rec.last.headers["X-Trace"] == "abc"
    assert rec.last.headers["Authorization"] == "Bearer other"  # default_headers win


def test_the_key_is_not_in_the_repr() -> None:
    client = make_client(Recorder(), api_key="dv_live_secret")
    assert "dv_live_secret" not in repr(client)
    assert "dv_live_secret" not in repr(client._transport.config)


def test_context_manager_closes_its_own_client() -> None:
    with LifeAstro(api_key="dv_live_test") as client:
        http = client._transport._http
    assert http.is_closed


def test_does_not_close_a_client_you_pass_in() -> None:
    http = httpx.Client(transport=httpx.MockTransport(Recorder()))
    with LifeAstro(api_key="dv_live_test", http_client=http) as client:
        client.meta.version()
    assert not http.is_closed
    http.close()


# ---------------------------------------------------------------------------
# query encoding
# ---------------------------------------------------------------------------
def test_keeps_a_legitimate_zero() -> None:
    rec = Recorder()
    make_client(rec).panchang.tithi(lat=0, lon=0, tz="UTC")
    assert rec.params()["lat"] == "0"
    assert rec.params()["lon"] == "0"


def test_url_encodes_a_fixed_offset_tz() -> None:
    rec = Recorder()
    make_client(rec).panchang.tithi(lat=1, lon=2, tz="+05:30")
    assert b"tz=%2B05%3A30" in rec.last.url.query
    assert rec.params()["tz"] == "+05:30"


def test_percent_encodes_path_parameters() -> None:
    rec = Recorder()
    make_client(rec).chart.planet(**BIRTH, name="a b/c")
    assert rec.last.url.raw_path.split(b"?")[0] == b"/v1/chart/planet/a%20b%2Fc"


def test_booleans_and_numbers_are_sent_like_the_node_sdk() -> None:
    rec = Recorder()
    make_client(rec).chart.sensitivity(**BIRTH, window=60, topocentric_moon=True)
    make_client(rec).chart.yogas(**BIRTH, all=False)
    assert rec.params(0)["topocentric_moon"] == "true"
    assert rec.params(0)["window"] == "60"
    assert rec.params(1)["all"] == "false"
    assert encode_query({"a": 5.0, "b": 19.076, "c": None, "d": "", "e": 0}) == "?a=5&b=19.076&e=0"


def test_non_ascii_values_are_utf8_encoded() -> None:
    rec = Recorder()
    make_client(rec).numerology.full(name="अर्जुन मेहता", dob="1990-01-15")
    assert rec.params()["name"] == "अर्जुन मेहता"


# ---------------------------------------------------------------------------
# escape hatch and response bodies
# ---------------------------------------------------------------------------
def test_request_hits_an_arbitrary_path() -> None:
    rec = Recorder(lambda _r: reply({"data": {"v": 1}}))
    client = make_client(rec)
    assert client.request("/v1/anything", {"a": "b"}) == {"v": 1}
    assert rec.last.url.path == "/v1/anything"
    assert rec.params()["a"] == "b"
    assert client.get("v1/x") == {"v": 1}
    assert rec.last.url.path == "/v1/x"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ([1, 2, 3], [1, 2, 3]),
        ({"foo": 1, "bar": 2}, {"foo": 1, "bar": 2}),
    ],
)
def test_non_enveloped_bodies_are_returned_as_is(body: Any, expected: Any) -> None:
    rec = Recorder(lambda _r: reply(body))
    assert make_client(rec).request("/v1/raw") == expected


def test_empty_body_is_none() -> None:
    rec = Recorder(lambda _r: httpx.Response(204))
    assert make_client(rec).request("/v1/empty") is None


# ---------------------------------------------------------------------------
# date defaults (the API has no "today" default)
# ---------------------------------------------------------------------------
def test_fills_todays_date_for_a_moment_endpoint() -> None:
    rec = Recorder()
    make_client(rec).panchang.tithi(lat=19.076, lon=72.8777, tz="Asia/Kolkata")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", rec.params()["date"])


def test_keeps_an_explicit_date() -> None:
    rec = Recorder()
    make_client(rec).panchang.tithi(lat=19.076, lon=72.8777, tz="Asia/Kolkata", date="2026-11-20")
    assert rec.params()["date"] == "2026-11-20"


def test_today_in_resolves_the_zone_and_falls_back_to_utc() -> None:
    now = datetime(2026, 3, 1, 20, 0, tzinfo=timezone.utc)  # already 2 March in Kolkata
    assert today_in("Asia/Kolkata", now) == "2026-03-02"
    assert today_in("America/Los_Angeles", now) == "2026-03-01"
    assert today_in("+05:30", now) == "2026-03-02"
    assert today_in("-04:00", now) == "2026-03-01"
    assert today_in("UTC+5:30", now) == "2026-03-02"
    assert today_in("Not/AZone", now) == "2026-03-01"
    assert today_in(None, now) == "2026-03-01"


def test_transit_positions_needs_no_arguments() -> None:
    rec = Recorder()
    make_client(rec).transit.positions()
    assert rec.params()["tz"] == "UTC"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", rec.params()["date"])


# ---------------------------------------------------------------------------
# endpoints corrected against the live API (Node 0.5.0)
# ---------------------------------------------------------------------------
def test_personal_horoscope_sends_the_chart_unprefixed_and_the_day_as_transit_date() -> None:
    rec = Recorder()
    make_client(rec).narrative.horoscope_daily_by_lagna(**BIRTH, on_date="2026-10-10")
    q = rec.params()
    assert q["date"] == "1990-01-15"
    assert q["transit_date"] == "2026-10-10"
    assert "birth.date" not in q


def test_reports_take_name_and_place_for_the_cover() -> None:
    rec = Recorder()
    client = make_client(rec)
    client.reports.kundli_lite(**BIRTH, name="Arjun Mehta", place="Mumbai")
    assert rec.params(0)["name"] == "Arjun Mehta"
    assert rec.params(0)["place"] == "Mumbai"
    client.reports.match_making(boy=BIRTH, girl=GIRL, boy_name="A", girl_name="B", boy_place="Pune")
    q = rec.params(1)
    assert (q["boy.name"], q["girl.name"], q["boy.place"]) == ("A", "B", "Pune")
    assert q["girl.date"] == "1992-03-20"


def test_monthly_horoscope_report_takes_month_as_yyyy_mm() -> None:
    rec = Recorder()
    make_client(rec).reports.horoscope_monthly(rashi="Aries", month="2026-11")
    assert rec.params()["month"] == "2026-11"
    assert "year" not in rec.params()


def test_meta_catalogs() -> None:
    rec = Recorder()
    client = make_client(rec)
    client.meta.endpoints()
    client.meta.vedic_yogas()
    assert [r.url.path for r in rec.requests] == ["/v1/meta/endpoints", "/v1/meta/vedic/yogas"]


MOMENT: dict[str, Any] = {
    "birth": BIRTH,
    "date": "2027-01-15",
    "time": "06:00",
    "tz": "Asia/Kolkata",
}
NATAL_TRANSIT: list[tuple[str, Callable[[LifeAstro], Any], bool]] = [
    ("/v1/vedic/narrative/transit-phal", lambda c: c.narrative.transit_phal(**MOMENT), True),
    ("/v1/vedic/narrative/dasha-phal", lambda c: c.narrative.dasha_phal(**MOMENT), True),
    ("/v1/vedic/narrative/transit-double", lambda c: c.narrative.transit_double(**MOMENT), False),
    (
        "/v1/vedic/narrative/sade-sati-status",
        lambda c: c.narrative.sade_sati_status(**MOMENT),
        False,
    ),
    ("/v1/vedic/narrative/sade-sati-phase", lambda c: c.narrative.sade_sati_phase(**MOMENT), False),
    (
        "/v1/vedic/narrative/sade-sati-history",
        lambda c: c.narrative.sade_sati_history(**MOMENT),
        False,
    ),
    ("/v1/ashtakavarga/kaksha", lambda c: c.ashtakavarga.kaksha(**MOMENT), False),
    ("/v1/ashtakavarga/transit-score", lambda c: c.ashtakavarga.transit_score(**MOMENT), False),
    ("/v1/transit/small-panoti", lambda c: c.transit.small_panoti(**MOMENT), False),
]


@pytest.mark.parametrize(
    ("path", "call", "place"), NATAL_TRANSIT, ids=[n[0] for n in NATAL_TRANSIT]
)
def test_natal_chart_and_transit_moment_are_separate(
    path: str, call: Callable[[LifeAstro], Any], place: bool
) -> None:
    rec = Recorder()
    call(make_client(rec))
    assert rec.last.url.path == path
    q = rec.params()
    assert q["birth.date"] == "1990-01-15"
    assert q["birth.time"] == "10:30"
    assert q["birth.lat"] == "19.076"
    assert q["date"] == "2027-01-15"
    assert q["tz"] == "Asia/Kolkata"
    # Endpoints that cast the natal lagna read the birth place unprefixed.
    assert q.get("lat") == ("19.076" if place else None)


def test_narrative_prashna() -> None:
    rec = Recorder()
    make_client(rec).narrative.prashna(
        lat=19.076, lon=72.8777, tz="Asia/Kolkata", date="2027-01-15", time="10:00",
        topic="career", question_house=10, lang="hi",
    )  # fmt: skip
    assert rec.last.url.path == "/v1/vedic/narrative/prashna"
    q = rec.params()
    assert (q["date"], q["time"], q["topic"], q["question_house"], q["locale"]) == (
        "2027-01-15", "10:00", "career", "10", "hi",
    )  # fmt: skip


# ---------------------------------------------------------------------------
# chart, transit, remedy and milan data endpoints (Node 0.5.0)
# ---------------------------------------------------------------------------
def test_chart_data_bundles_read_the_birth_chart_unprefixed() -> None:
    cases: list[tuple[str, Callable[[LifeAstro], Any], dict[str, str]]] = [
        ("/v1/chart/kundli-facts", lambda c: c.chart.kundli_facts(**BIRTH, vargas="D9,D10", include="all", gender="male"), {"vargas": "D9,D10", "include": "all", "gender": "male"}),
        ("/v1/chart/yogas", lambda c: c.chart.yogas(**BIRTH, all=True), {"all": "true"}),
        ("/v1/chart/doshas", lambda c: c.chart.doshas(**BIRTH, gender="female"), {"gender": "female"}),
        ("/v1/chart/sensitivity", lambda c: c.chart.sensitivity(**BIRTH, window=60, vargas="D9", topocentric_moon=True), {"window": "60", "vargas": "D9", "topocentric_moon": "true"}),
    ]  # fmt: skip
    for path, call, extra in cases:
        rec = Recorder()
        call(make_client(rec))
        q = rec.params()
        assert rec.last.url.path == path
        assert (q["date"], q["time"], q["lat"]) == ("1990-01-15", "10:30", "19.076")
        assert "birth.date" not in q
        for key, value in extra.items():
            assert q[key] == value


def test_sade_sati_windows() -> None:
    rec = Recorder()
    make_client(rec).transit.sade_sati_windows(
        birth={"date": "1990-01-15", "time": "10:30", "tz": "Asia/Kolkata"},
        from_="2027-01-15", tz="UTC", years=30, include_past=True,
    )  # fmt: skip
    q = rec.params()
    assert rec.last.url.path == "/v1/transit/sade-sati/windows"
    assert (q["birth.date"], q["birth.time"], q["birth.tz"]) == (
        "1990-01-15",
        "10:30",
        "Asia/Kolkata",
    )
    assert "birth.lat" not in q and "date" not in q
    assert (q["from"], q["tz"], q["years"], q["include_past"]) == (
        "2027-01-15",
        "UTC",
        "30",
        "true",
    )


def test_transit_windows_planet_required_birth_optional() -> None:
    rec = Recorder()
    client = make_client(rec)
    client.transit.windows(planet="jupiter", from_="2027-01-15", years=12)
    q = rec.params(0)
    assert (q["planet"], q["from"], q["years"]) == ("jupiter", "2027-01-15", "12")
    assert not any(k.startswith("birth.") for k in q)
    client.transit.windows(planet="saturn", birth=BIRTH)
    q = rec.params(1)
    assert (q["birth.date"], q["birth.lat"], q["birth.lon"]) == ("1990-01-15", "19.076", "72.8777")
    assert "lat" not in q


def test_remedies_for_graha() -> None:
    rec = Recorder()
    make_client(rec).remedies.for_graha(
        graha="saturn",
        reason="dosha:sade_sati",
        include="pooja,yantra",
        category="mantra",
        lang="hi",
    )
    q = rec.params()
    assert rec.last.url.path == "/v1/vedic/remedies/for-graha"
    assert (q["graha"], q["reason"], q["include"], q["category"], q["locale"]) == (
        "saturn", "dosha:sade_sati", "pooja,yantra", "mantra", "hi",
    )  # fmt: skip


def test_milan_overlay_and_summary() -> None:
    rec = Recorder()
    client = make_client(rec)
    client.milan.overlay(boy=BIRTH, girl=GIRL)
    assert rec.requests[0].url.path == "/v1/milan/overlay"
    assert (rec.params(0)["boy.date"], rec.params(0)["girl.lat"]) == ("1990-01-15", "28.6139")
    client.milan.summary(
        boy=BIRTH, girl=GIRL, from_="2027-01-15", tz="Asia/Kolkata", include="kundli_facts"
    )
    q = rec.params(1)
    assert (q["boy.time"], q["girl.time"], q["from"], q["include"]) == (
        "10:30",
        "08:15",
        "2027-01-15",
        "kundli_facts",
    )


def test_milan_dasha_sync() -> None:
    rec = Recorder()
    make_client(rec).milan.dasha_sync(
        boy=BIRTH, girl=GIRL, timeline=True, years=5, from_="2027-01-15",
        marriage_windows=True, date="2027-02-01", tz="Asia/Kolkata",
    )  # fmt: skip
    q = rec.params()
    assert q["boy.lat"] == "19.076"
    assert q["girl.lon"] == "77.209"
    assert (q["timeline"], q["years"], q["from"], q["marriage_windows"]) == (
        "true",
        "5",
        "2027-01-15",
        "true",
    )
    assert (q["date"], q["tz"]) == ("2027-02-01", "Asia/Kolkata")


# ---------------------------------------------------------------------------
# optional params the API reads (added to the shared manifest)
# ---------------------------------------------------------------------------
def test_best_time_purpose_top_n_birth_date_ayanamsa() -> None:
    rec = Recorder()
    make_client(rec).muhurta.best_time(
        lat=19.076, lon=72.8777, tz="Asia/Kolkata", start_date="2027-01-15", end_date="2027-01-31",
        purpose="vivah", top_n=3, birth_date="1990-01-15", ayanamsa="raman",
    )  # fmt: skip
    q = rec.params()
    assert (q["purpose"], q["top_n"], q["birth_date"], q["ayanamsa"]) == (
        "vivah",
        "3",
        "1990-01-15",
        "raman",
    )


def test_at_on_current_dashas_and_week_on_the_weekly_report() -> None:
    rec = Recorder()
    client = make_client(rec)
    client.dasha.char_current(**BIRTH, at="2027-01-15T06:00:00Z")
    client.lalkitab.dasha_current(**BIRTH, at="2027-01-15")
    client.reports.horoscope_weekly(rashi="Aries", week="2026-W47")
    assert rec.params(0)["at"] == "2027-01-15T06:00:00Z"
    assert rec.params(1)["at"] == "2027-01-15"
    assert rec.params(2)["week"] == "2026-W47"


def test_western_orbs_rulership_house_system_composite_relocation() -> None:
    rec = Recorder()
    client = make_client(rec)
    client.western.natal.chart(**BIRTH, orb_trine=6, orb_sextile=4, rulership="traditional")
    client.western.synastry.aspects(
        person_a=BIRTH, person_b=GIRL, house_system="koch", orb_conjunction=8
    )
    client.western.transits.to_natal(
        birth=BIRTH, date="2027-01-15", time="06:00", tz="UTC", orb_square=5
    )
    client.western.composite.chart(person_a=BIRTH, person_b=GIRL, composite_method="midpoint_cusps")
    client.western.returns.solar(**BIRTH, return_year=2027, relocate_lat=51.5, relocate_lon=-0.12)
    assert (
        rec.params(0)["orb_trine"],
        rec.params(0)["orb_sextile"],
        rec.params(0)["rulership"],
    ) == ("6", "4", "traditional")
    assert (rec.params(1)["house_system"], rec.params(1)["orb_conjunction"]) == ("koch", "8")
    assert (rec.params(2)["orb_square"], rec.params(2)["birth.date"]) == ("5", "1990-01-15")
    assert rec.params(3)["composite_method"] == "midpoint_cusps"
    assert (rec.params(4)["relocate_lat"], rec.params(4)["relocate_lon"]) == ("51.5", "-0.12")


def test_ayanamsa_on_calendar_and_planet_moments() -> None:
    rec = Recorder()
    client = make_client(rec)
    client.calendar.ritu(date="2027-01-15", tz="Asia/Kolkata", ayanamsa="raman")
    client.planet_moments.ingress(
        planet="Jupiter", date="2027-01-15", tz="Asia/Kolkata", ayanamsa="krishnamurti"
    )
    assert rec.params(0)["ayanamsa"] == "raman"
    assert rec.params(1)["ayanamsa"] == "krishnamurti"


# ---------------------------------------------------------------------------
# on_response (credits, rate limit, request id)
# ---------------------------------------------------------------------------
RESPONSE_HEADERS = {
    "X-Request-ID": "52a520f261d3db37",
    "X-Credits-Remaining": "64043",
    "X-RateLimit-Limit": "250",
    "X-RateLimit-Remaining": "249",
    "X-RateLimit-Reset": "1794718800",
    "X-Cache": "HIT",
    "Content-Language": "gu",
}
FULL_INFO = ResponseInfo(
    status=200,
    path="/v1/panchang/basic",
    request_id="52a520f261d3db37",
    credits_remaining=64043,
    rate_limit=RateLimit(
        limit=250, remaining=249, reset_at=datetime.fromtimestamp(1794718800, tz=timezone.utc)
    ),
    cache="HIT",
    language="gu",
)


def test_on_response_reports_every_header_client_level_and_per_call() -> None:
    rec = Recorder(lambda _r: reply({"ok": 1}, headers=RESPONSE_HEADERS))
    seen: list[ResponseInfo] = []
    per_call: list[ResponseInfo] = []
    order: list[str] = []

    def client_hook(info: ResponseInfo) -> None:
        seen.append(info)
        order.append("client")

    def call_hook(info: ResponseInfo) -> None:
        per_call.append(info)
        order.append("call")

    client = make_client(rec, on_response=client_hook)
    client.panchang.basic(
        lat=1, lon=2, tz="UTC", lang="gu", request_options={"on_response": call_hook}
    )
    assert seen == [FULL_INFO]
    assert per_call == seen
    assert order == ["client", "call"]
    assert seen[0].rate_limit is not None
    assert seen[0].rate_limit.reset_at.tzinfo == timezone.utc


def test_on_response_leaves_out_headers_the_api_did_not_send() -> None:
    # Free calls have no credits header; a non-numeric value or an incomplete
    # rate-limit set is left out too.
    headers = {
        "x-request-id": "abc",
        "x-credits-remaining": "n/a",
        "x-ratelimit-limit": "250",
        "x-ratelimit-remaining": "249",
    }
    rec = Recorder(lambda _r: reply({"ok": 1}, headers=headers))
    seen: list[ResponseInfo] = []
    make_client(rec, on_response=seen.append).meta.version()
    assert seen == [ResponseInfo(status=200, path="/v1/meta/version", request_id="abc")]


def test_on_response_reports_the_final_error_once_not_the_retried_attempts() -> None:
    calls = {"n": 0}

    def unavailable(_r: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        body = {"error": {"code": "billing_unavailable", "message": "x"}}
        return reply(body, 503, {"x-request-id": f"r{calls['n']}", "retry-after": "0"})

    seen: list[ResponseInfo] = []
    client = make_client(Recorder(unavailable), max_retries=2, on_response=seen.append)
    with pytest.raises(ServerError):
        client.meta.version()
    assert calls["n"] == 3
    assert [(i.status, i.request_id) for i in seen] == [(503, "r3")]


def test_on_response_is_not_called_for_a_network_failure() -> None:
    # The 503 was retried and the retry failed without a response: nothing to report.
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return reply({"error": {"code": "unavailable"}}, 503, {"x-request-id": "r1"})
        raise httpx.ConnectError("boom", request=request)

    seen: list[ResponseInfo] = []
    client = make_client(Recorder(flaky), max_retries=1, on_response=seen.append)
    with pytest.raises(LifeAstroConnectionError):
        client.meta.version()
    assert calls["n"] == 2
    assert seen == []


def test_a_raising_on_response_hook_never_breaks_the_call() -> None:
    def broken(_info: ResponseInfo) -> None:
        raise RuntimeError("logger down")

    rec = Recorder(lambda _r: reply({"v": 7}, headers=RESPONSE_HEADERS))
    client = make_client(rec, on_response=broken)
    assert client.meta.version(request_options={"on_response": broken}) == {"v": 7}
