# lifeastroapi

Official **Python SDK** for [LifeAstroAPI](https://lifeastroapi.com): a REST
[astrology API](https://lifeastroapi.com/apis/) for Vedic astrology, panchang, Hindu festivals,
kundli, kundli matching, muhurat, dashas, horoscopes, numerology, tarot and Western charts, with
location-aware calculations and pay-per-call billing. Free tier: 1,500 credits a month, no card.
[Get a key](https://lifeastroapi.com/signup/).

- **Every endpoint**: 322 methods across 23 resource groups (panchang, chart, dasha, milan,
  transit, horoscope, numerology, muhurta, reports, narrative, remedies, a complete Western
  module and more). Same methods as the official Node.js SDK, generated from the same manifest.
- **Sync and async**: `LifeAstro` and `AsyncLifeAstro`, both on [httpx](https://www.python-httpx.org/),
  the only runtime dependency.
- **10 languages**: Vedic methods answer in `en`, `hi`, `mr`, `gu`, `bn`, `te`, `ta`, `kn`, `ml`
  and `pa` with `lang=`.
- **Typed**: full type hints and `py.typed`; keyword arguments with `Literal` types for
  languages, ayanamsas and house systems. Passes `mypy --strict`.
- Typed errors, automatic retries (429, 5xx and network errors) that honour `Retry-After`,
  timeouts, and an escape hatch for any endpoint.
- Python 3.9 and later.

```bash
pip install lifeastroapi
```

Get an API key at **https://lifeastroapi.com/dashboard/keys**.

## Quick start

```python
from lifeastroapi import LifeAstro

client = LifeAstro(api_key="dv_live_...")
# or: LifeAstro()  reads the LIFEASTRO_API_KEY environment variable

# Today's panchang for Ahmedabad, in Gujarati
day = client.panchang.basic(lat=23.0225, lon=72.5714, tz="Asia/Kolkata", lang="gu")
print(day["tithi"]["name"], day["nakshatra"]["name"], day["vara"]["weekday"])
# for example: પંચમી પૂર્વાષાઢા શનિવાર

# A Vedic birth chart
chart = client.chart.planets(
    date="1990-01-15", time="10:30", tz="Asia/Kolkata", lat=19.076, lon=72.8777
)
for planet in chart["planets"]:
    print(planet["name"], planet["house"], planet["dms_in_sign"])

# Kundli matching score
match = client.milan.ashtakoota_total(
    boy={
        "date": "1990-01-15",
        "time": "10:30",
        "tz": "Asia/Kolkata",
        "lat": 19.076,
        "lon": 72.8777,
    },
    girl={
        "date": "1992-03-20",
        "time": "08:15",
        "tz": "Asia/Kolkata",
        "lat": 28.6139,
        "lon": 77.209,
    },
)
print(match["total"], "/", match["max"])
```

### Async

```python
import asyncio
from lifeastroapi import AsyncLifeAstro


async def main() -> None:
    async with AsyncLifeAstro() as client:
        kolkata, festivals = await asyncio.gather(
            client.panchang.basic(lat=22.5726, lon=88.3639, tz="Asia/Kolkata", lang="bn"),
            client.festivals.month(year=2027, month=1, lat=22.5726, lon=88.3639, lang="bn"),
        )
    print(kolkata["tithi"]["name"])
    for festival in festivals["festivals"][:5]:
        print(festival["date"], festival["name"])


asyncio.run(main())
```

Every method of `LifeAstro` exists on `AsyncLifeAstro` with the same arguments, as a coroutine.

More in [examples/](https://github.com/ayanshulife/lifeastroapi-python/tree/main/examples):
quick start, async calls, and error handling.

## Authentication

Your API key (`dv_live_...`) is sent as an `Authorization: Bearer ...` header on every request.

```python
LifeAstro(api_key="dv_live_...")  # 1. explicit
LifeAstro("dv_live_...")  # 2. first argument
LifeAstro()  # 3. reads LIFEASTRO_API_KEY
```

Without a key the constructor raises `LifeAstroError` (code `missing_api_key`).

> **Keep the key on your server.** A `dv_live_...` key carries your account's full billing
> access. Use this SDK from a server, a background job or a serverless function, and load the
> key from an environment variable or a secrets manager. Do not ship it inside a desktop or
> mobile app, where users could extract it. For client apps, call LifeAstroAPI from your own
> backend and forward the results.

## Configuration

```python
import httpx
from lifeastroapi import LifeAstro

client = LifeAstro(
    api_key="dv_live_...",  # or set LIFEASTRO_API_KEY
    base_url="https://api.lifeastroapi.com",  # e.g. http://localhost:8080 for local work
    timeout=30.0,  # seconds per request (default 30)
    max_retries=2,  # retries on 429 / 5xx / network errors (default 2)
    default_headers={"X-Request-Source": "my-app"},  # extra headers on every request
    http_client=httpx.Client(proxy="http://proxy:3128"),  # optional; your own httpx client
    on_response=None,  # optional; see "Credits, rate limit and request id"
)
```

Both clients are context managers (`with` / `async with`) and have `close()`
(a coroutine on `AsyncLifeAstro`). The SDK closes only the httpx client it created itself, never
one you pass in.

## Arguments

Every method takes **keyword arguments**. The SDK turns them into the exact query parameters
the API expects (`birth.lat`, `boy.date`, `start_date`, ...).

| Input | Used by | Arguments |
|-------|---------|-----------|
| **Moment** | `panchang.*`, `muhurta.*` (one date), `prashna.*`, `narrative.prashna` | `lat, lon, tz, date=None, time=None` |
| **Instant** | `transit.positions`, `transit.double_transit`, `meta.ayanamsas` | `date=None, time=None, tz=None` |
| **Birth** | `chart.*`, `dasha.*`, narratives, reports | `date, time, tz, lat, lon` |
| **Boy / girl** | `milan.*`, `reports.match_making` | `boy={...}, girl={...}` |
| **Two people** | `western.synastry.*`, `western.composite.*` | `person_a={...}, person_b={...}` |
| **Rashi** | `horoscope.*` | `rashi="aries", date=None, lang=None` |
| **Date range** | `eclipses.*`, `western.ingresses` | `start_date, end_date` |
| **Muhurta search** | `muhurta.best_time` | `lat, lon, tz, start_date, end_date, purpose=None, top_n=None, birth_date=None` |
| **Natal + window** | `transit.sade_sati_windows`, `transit.windows` | `birth={...}, from_=None, tz=None` |
| **Natal + transit** | `transit.tarabala`, `transit.vedha`, `transit.small_panoti`, `ashtakavarga.kaksha`, `ashtakavarga.transit_score`, `western.transits.to_natal`, `narrative.transit_phal`, `narrative.dasha_phal`, `narrative.sade_sati_status`, ... | `birth={...}, date, time, tz` |

`boy`, `girl`, `person_a`, `person_b` and `birth` are plain dicts with `date` (`YYYY-MM-DD`),
`time` (`HH:MM`), `tz` (IANA name such as `Asia/Kolkata`, or an offset such as `+05:30`),
`lat` and `lon`. The `BirthInput` type describes them:

```python
from lifeastroapi import BirthInput

arjun: BirthInput = {
    "date": "1990-01-15",
    "time": "10:30",
    "tz": "Asia/Kolkata",
    "lat": 19.076,
    "lon": 72.8777,
}
client.chart.planets(**arjun)  # unprefixed date / time / tz / lat / lon
client.milan.mangal_dosha(**arjun)  # sent as birth.date, birth.time, ...
client.transit.tarabala(birth=arjun, date="2027-01-15", time="06:00", tz="Asia/Kolkata")
```

**Names.** Method and argument names are the Node SDK's names in snake_case:
`ashtakootaTotal` is `ashtakoota_total`, `houseSystem` is `house_system`. Most arguments have
the same name as their query parameter. Where they differ, the method's docstring lists the
wire name; for example `narrative.horoscope_daily_by_lagna(on_date=...)` sends `transit_date`,
and `from_` (a Python keyword) sends `from`.

**Dates.** The API needs a `date` on every moment endpoint. Where the argument is optional, the
SDK sends today's date in the `tz` you gave (`transit.positions()` with no arguments uses UTC).

**Settings.** Vedic methods accept `ayanamsa` (`"lahiri"` by default, `"krishnamurti"`,
`"raman"`, ...) and chart methods `house_system`.

```python
client.chart.planets(**arjun, ayanamsa="krishnamurti", house_system="placidus")
```

**Data endpoints** (`chart.kundli_facts`, `chart.yogas`, `chart.doshas`, `chart.sensitivity`,
`transit.sade_sati_windows`, `transit.windows`, `remedies.for_graha`, `milan.overlay`,
`milan.summary`) return ids and numbers, no prose: planet ids `sun` ... `ketu`, `sign_index`
0-based (0 = Aries), `house` 1-based whole-sign from the lagna, every instant as `*_local`
(RFC 3339) plus `*_jd` (Julian Day, UT).

## Languages

Every Vedic method whose response carries names or text takes an optional `lang`. The same
fields come back in that language; ids, dates, numbers and explicit `*_en` / `*_hi` fields do
not change.

```python
day = client.panchang.basic(
    lat=19.076, lon=72.8777, tz="Asia/Kolkata", date="2027-01-15", lang="mr"
)
chart = client.chart.planets(**arjun, lang="ta")
```

| `lang` | Language | Coverage |
|--------|----------|----------|
| `en` | English (default) | complete |
| `hi` | Hindi | complete |
| `mr` | Marathi | complete |
| `gu` | Gujarati | complete |
| `bn` | Bengali | complete |
| `te` | Telugu | complete |
| `ta` | Tamil | complete |
| `kn` | Kannada | complete |
| `ml` | Malayalam | complete |
| `pa` | Punjabi | names and terms; longer prose is still English |

- The `Locale` type lists the codes, and `LOCALES` holds them as a tuple.
- **Where it works:** `panchang`, `calendar`, `festivals`, `eclipses`, `planet_moments`,
  `transit`, `milan`, `muhurta`, `chart`, `prashna`, `numerology`, `dasha`, `varshaphal`,
  `ashtakavarga`, `lalkitab`, `horoscope`, `reports`, `narrative` and `remedies`.
  `festivals.*`, `panchang.monthly` and some `remedies.*` methods also accept the older
  `locale` argument; `lang` wins when both are given.
- **Methods without `lang`:** those that return only times, numbers or ids, such as
  `panchang.rahu_kaal`, `panchang.sunrise_sunset`, `chart.yogas`, `chart.doshas`,
  `transit.windows` and `milan.overlay`. There is nothing in them to translate.
- **English only:** `western.*`, `tarot.*`, `geo.*` and `meta.*`. The `western.narrative.*`
  methods take `lang` for `en`, `hi` and `mr`.

## Resource groups

`client.<group>.<method>(...)` returns the response as parsed JSON (`dict` or `list`).

| Group | What it covers |
|-------|----------------|
| `panchang` | tithi, nakshatra, yoga, karana, vara, sunrise/sunset, rahu kaal, choghadiya, hora, muhurtas, monthly calendar, composite `basic` / `advanced` |
| `chart` | planets, ascendant, houses, divisional (D1-D60), dignity, aspects, shadbala, ashtakvarga, avakhada, KP, astro details; data bundles `kundli_facts`, `yogas`, `doshas`, birth-time `sensitivity` |
| `dasha` | Vimshottari (full, current, 5-level drill-down), Yogini and Chara dashas |
| `milan` | Ashtakoota (total, full, per koota), mangal / nadi / shani dosha, navamsa and dasha compatibility, `overlay`, `summary` |
| `transit` | positions, sade sati, ashtakavarga, tarabala, vedha, double transit, small panoti, `sade_sati_windows`, `windows` |
| `horoscope` | daily, weekly, monthly by rashi |
| `numerology` | driver, conductor, soul, personality, destiny, full, advanced, challenges, personal periods |
| `muhurta` | vivah, naamkaran, griha pravesh, vyapar, yatra, best time, chandra / tara bala |
| `varshaphal` | annual chart, lord, muntha, mudda dasha, harsha bala, tajika yogas |
| `prashna` | horary answer, chart, arudha, significators |
| `eclipses` | solar, lunar, all (date range, local contacts and sutak) |
| `calendar` | Hindu month, ritu, samvatsara, adhik maas, solstices |
| `festivals` | Hindu festivals by month, on a date, or by vrat family; `lang`, `month_system` (amanta / purnimanta) |
| `planet_moments` | retrograde windows, ingress, combustion window, speed |
| `ashtakavarga` | sarva, bhinna (per planet), kaksha, transit score |
| `geo` | place search, reverse geocoding, time zone, place by id |
| `tarot` | cards, one card, daily card, spread, yes / no |
| `reports` | JSON reports: kundli (lite, detailed, brihad), match making, mangal dosha, sade sati, varshaphal, numerology, horoscopes |
| `narrative` | authored Vedic readings (lagna, planets, yogas, doshas, dasha phal, transit phal, prashna, horoscopes, ...) |
| `remedies` | remedies by rule id, `for_graha`, mantra, pooja, vrat, daan, rudraksha, yantra, Lal Kitab |
| `lalkitab` | Lal Kitab chart and dasha |
| `meta` | free catalogs: `endpoints` (credit cost of every route), `ayanamsas`, `vedic_yogas`, `vedic_doshas`, `vedic_locales`, `version` |
| `western` | the full tropical module (below) |

### Western (tropical)

```python
priya: BirthInput = {
    "date": "1992-03-20",
    "time": "08:15",
    "tz": "Asia/Kolkata",
    "lat": 28.6139,
    "lon": 77.209,
}

client.western.natal.chart(**arjun, house_system="placidus")
client.western.synastry.score(person_a=arjun, person_b=priya)
client.western.transits.to_natal(birth=arjun, date="2026-06-16", time="12:00", tz="UTC")
client.western.returns.solar(**arjun, return_year=2026)
client.western.profections.annual(birth_date="1990-01-15", asc_sign="capricorn")
```

Sub-groups: `natal`, `horoscope`, `synastry`, `composite`, `davison`, `transits`,
`progressions`, `solar_arc`, `returns`, `dignities`, `profections`, `zodiacal_releasing`,
`primary_directions`, `interpretation`, `narrative`, `heliocentric`, `astrocartography`,
`eclipses`, `lunar`, `compatibility`, plus `firdaria`, `ingresses` and `retrograde_window`.

Each method's docstring has the endpoint description, its credit cost and its path. The costs
are a snapshot taken when this version was built; `client.meta.endpoints()` returns the live
cost of every route.

## Error handling

Every non-2xx response raises a typed error carrying the API's `code`, the HTTP `status` and the
`request_id`:

```python
from lifeastroapi import LifeAstroError, PaymentRequiredError, RateLimitError

try:
    client.chart.planets(**arjun)
except PaymentRequiredError:
    ...  # 402: out of credits
except RateLimitError as err:
    print(f"retry after {err.retry_after}s")
except LifeAstroError as err:
    print(err.code, err.status, err.message, err.request_id)
```

| Error | When |
|-------|------|
| `BadRequestError` | 400: a parameter is missing, malformed or out of range |
| `AuthenticationError` | 401: missing or invalid key |
| `PaymentRequiredError` | 402: out of credits |
| `PermissionDeniedError` | 403: key not allowed (plan, IP allow-list, suspended) |
| `NotFoundError` | 404: unknown path or id |
| `RateLimitError` | 429: rate limit or daily quota; `retry_after` in seconds |
| `ServerError` | 5xx |
| `LifeAstroConnectionError` | network failure, no response (`status == 0`) |
| `LifeAstroTimeoutError` | the request timed out (a `LifeAstroConnectionError`) |

All of them extend `LifeAstroError`. Requests are retried automatically (`max_retries`, default
2) on 408, 425, 429, 500, 502, 503, 504, network errors and timeouts, with exponential backoff
(0.5 s, 1 s, 2 s, ... up to 8 s) or the server's `Retry-After` (up to 30 s).

## Responses

Methods return the parsed JSON body (`dict` or `list`), typed `Any`. The API has hundreds of
response shapes and they grow over time, so the SDK does not wrap them in classes. Annotate the
fields you use in your own code, for example with a `TypedDict`.

## Per-call options

```python
client.chart.planets(**arjun, request_options={"timeout": 5})
client.request("/v1/panchang/tithi", {...}, request_options={"raw": True})
```

`timeout` overrides the client timeout for one call; `raw` returns the body exactly as received;
`on_response` is the hook below, for one call.

## Credits, rate limit and request id

Every response carries your credit balance, your plan's rate limit and a request id in its
headers. `on_response` hands them to you as a `ResponseInfo`, for every call (client argument)
or for one call (`request_options`):

```python
from lifeastroapi import LifeAstro, ResponseInfo


def warn_when_low(info: ResponseInfo) -> None:
    if info.credits_remaining is not None and info.credits_remaining < 5_000:
        print(f"LifeAstroAPI credits low: {info.credits_remaining}")


client = LifeAstro(on_response=warn_when_low)

client.panchang.basic(
    lat=19.076,
    lon=72.8777,
    tz="Asia/Kolkata",
    request_options={
        "on_response": lambda info: print(
            info.request_id, info.rate_limit.remaining if info.rate_limit else None
        )
    },
)
```

| Field | From header | Meaning |
|---|---|---|
| `status` | | HTTP status |
| `path` | | Endpoint path, e.g. `/v1/panchang/basic` |
| `request_id` | `X-Request-ID` | Quote it to support |
| `credits_remaining` | `X-Credits-Remaining` | Balance after the call; unchanged after a failed call (failed calls are free). `None` on the free tier, whose allowance is daily/monthly rather than a balance |
| `rate_limit` | `X-RateLimit-*` | `RateLimit(limit, remaining, reset_at)` per minute for your plan; `reset_at` is a UTC `datetime` |
| `cache` | `X-Cache` | `HIT` when the API answered from its cache (billed the same) |
| `language` | `Content-Language` | Language of the answer |

A field is `None` when the API did not send its header. `ResponseInfo` and `RateLimit` are frozen
dataclasses. The hook runs once per call with the final response, success or error (not for
retried attempts or network failures); the client-level hook runs first, then the per-call one.
An exception raised inside it is ignored, so logging can never break a call. `AsyncLifeAstro`
takes the same `on_response`, a plain function (not a coroutine).

## Escape hatch

Call any `/v1/*` endpoint by its path and wire parameter names, for example one that is newer
than your SDK version:

```python
data = client.request(
    "/v1/panchang/tithi", {"lat": 28.61, "lon": 77.20, "tz": "Asia/Kolkata", "date": "2027-01-15"}
)
# client.get(...) is an alias
```

## PDF reports

The `reports.*` methods return the report JSON. Branded PDF rendering of those reports, which
the Node SDK offers in `lifeastroapi/pdf`, is planned for a later version of this package.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python scripts/generate.py                  # regenerate src/lifeastroapi/resources
.venv/bin/pytest                                      # unit tests (mock transport)
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy                                        # package, scripts, examples (Python 3.9)
.venv/bin/mypy --python-version 3.10 tests
```

`scripts/generate.py` reads the endpoint manifest of the Node SDK (`../lifeastroapi-node`,
through its `scripts/manifest.mjs`, so it needs `node`), so both SDKs always have the same
methods. `--costs-url <base url>` refreshes the credit costs from `GET /v1/meta/endpoints`.

`scripts/live_sweep.py` calls every method once against a real server and lists the calls the
API rejects. It spends credits (one call per endpoint) and has no default URL:

```bash
LIFEASTRO_API_KEY=dv_live_... .venv/bin/python scripts/live_sweep.py --base-url http://localhost:8080
```

## Links

- Documentation: https://lifeastroapi.com/docs/
- API reference: https://lifeastroapi.com/docs/reference/
- Node.js / TypeScript SDK: `npm install lifeastroapi`

## License

MIT
