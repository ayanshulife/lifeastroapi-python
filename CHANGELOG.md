# Changelog

## 1.1.0 — 2026-11-28

New methods. Nothing changes for code written against 1.0.0. The install is the same and has no
new dependency.

- `dasha.ashtottari`: the full Ashtottari dasha (108-year cycle of 8 lords) with the balance at
  birth and whether the chart meets the classical conditions. Options `depth` (1-3), `scheme`
  (`28` default or `27`) and `antar_start` (`maha_lord` default or `next_lord`). 10 credits.
- `dasha.ashtottari_current`: the Ashtottari mahadasha and antardasha running now, or at `at`.
  Same options. 10 credits.
- `chart.arudha_padas`: the twelve arudha padas (A1 to A12, with AL and UL) and how each was
  counted. Options `exception` (`parashari` default or `none`), `scorpio_lord` (`mars` or `ketu`)
  and `aquarius_lord` (`saturn` or `rahu`). 10 credits.
- `chart.upapada`: the Upapada Lagna with its lord, the planets in it and the planets that aspect
  it. Same options as `chart.arudha_padas`. 10 credits.
- `chart.argala`: argala and its obstruction on every house, or on one `house`. Options
  `include_eighth`, `node_reversal` (`ketu` default, `rahu_ketu` or `none`) and
  `vipareeta_min_malefics` (default 3). 10 credits.
- `muhurta.vahan`: score a moment for buying a vehicle or its first use. 20 credits.
- `muhurta.bhoomi_pujan`: score a moment for ground-breaking or laying a foundation. 20 credits.
- `muhurta.upanayan`: score a moment for the sacred thread ceremony. 20 credits.
- `muhurta.annaprashan`: score a moment for a child's first solid food. Optional `birth_date` and
  `sex` add a note on the child's age. 20 credits.
- `muhurta.vidyarambh`: score a moment for a child's first letters. Optional `birth_date` adds an
  age note. 20 credits.
- `muhurta.karnavedha`: score a moment for ear piercing. Optional `birth_date` adds an age note.
  20 credits.

**Changes to existing methods** (all optional, nothing to change in your code):

- `muhurta.best_time` takes the purposes `vyapar`, `yatra`, `vahan` and `bhoomi_pujan`, next to
  `general`, `vivah`, `graha_pravesh` and `naamkaran`, and a new `direction` argument (N, NE, E,
  SE, S, SW, W, NW) for `yatra`.
- `muhurta.yatra` takes a `direction` argument. When you leave it out, the API no longer assumes
  travel to the East: there is then no direction check.
- Every muhurta score now has `prohibited_by` in its `result`: the classical prohibitions that
  apply, as English ids such as `Bhadra`, `GuruShukraAsta` or `AdhikaMasa`. When the list is not
  empty, `grade` is `inauspicious` and `is_acceptable` is false. `muhurta.best_time` never returns
  a window under a prohibition, so it can return fewer windows than `top_n`.
- `muhurta.upanayan`, `muhurta.annaprashan`, `muhurta.vidyarambh` and `muhurta.karnavedha` also
  return `result.notes`: information such as the child's age by tradition or a festival on that
  day. Notes never change the score.

## 1.0.0 — 2026-11-27

This is the first stable release. From 1.0.0 on, a change that needs a code change on your side
only comes with a new major version. The install is the same and has no new dependency.

- **Easier key setup.** The API key is trimmed of spaces and line breaks around it, so a key read
  from a file or a quoted `.env` value works as it is.
- **The key never appears in an error message.** When the HTTP library rejects a request header,
  its message quoted the value. The SDK now replaces the key with `***` before raising
  `LifeAstroConnectionError`.
- **Clear error for a reply that is not JSON.** Such a reply did not come from the API: a proxy,
  firewall or CDN in between answered, usually with an HTML page. It now raises the error of its
  HTTP status with `code == "non_json_response"`; the message gives the status and the start of
  the body.
- README: what to do on a Python older than 3.9, the `proxy=` argument on older httpx, and the
  `non_json_response` error.

**Changes that may need a code change**

- A 200 reply with a body that is not JSON now raises instead of returning the text.
  Before: `text = client.request(path)` gave you the body as a `str`.
  Now: `except LifeAstroError as err:` with `err.code == "non_json_response"`; `err.body` holds
  the text.
- `numerology.full` requires `dob`. The API always required it; a call without it now raises
  `TypeError` before any request is made, instead of a 400 from the API.
  Before: `client.numerology.full(name="Arjun Mehta")` was accepted by the SDK.
  Now: `client.numerology.full(dob="1990-01-15", name="Arjun Mehta")`

## 0.3.0 — 2026-11-22

Upgrading from 0.2.0: your code keeps working. The install is the same and has no new dependency.

- **New: PDF reports.** `lifeastroapi.pdf` turns the JSON of every `client.reports.*` method into a
  branded PDF, in all 10 languages, with one call: `kundli_lite_pdf(report, branding)`,
  `match_making_pdf(...)`, and so on.
  - The PDF is made on your machine, with Chrome, Chromium or Microsoft Edge (found
    automatically) or with a Gotenberg service you run. Nothing is sent to LifeAstroAPI for it.
  - Your branding: company name and footer line as you wrote them, logo, colours, and a watermark
    on every page. The Brihad kundli follows your colours in headings, banners, contents, charts,
    header and footer, and is saffron without a brand. A colour too pale to read prints darker.
  - The Brihad kundli PDF has a table of contents with the real page numbers, a running header
    and footer with your company name and footer line, bookmarks in the report's language and the
    document title.
  - `PdfOptions` for margins (side by side), paper size, landscape, printing without backgrounds,
    your own header and footer, and timeouts. They apply to the reports and to your own HTML.
  - For many PDFs, keep one browser open with `ChromePdfEngine`. In `asyncio` code use the
    `*_pdf_async` functions: they do not block, and they stop when the task is cancelled.
  - Only need HTML, for a browser or an app's web view? The `render_*_html` functions need no
    browser and give the same HTML as the Node.js SDK. `A4_PRINT_OPTIONS` has the page size and
    margins.
  - A failed PDF raises `PdfError` (a `LifeAstroError`), whose `code` says what went wrong.
- **Fixed:** the `HouseSystem` type now has `"whole_sign"`, the name the API reads. The old
  `"whole-sign"` got a 400 error from the API until 2026-11-21. The API now accepts it as an
  alias and the type still lists it, so code that uses it keeps working and type-checking.
- **Punjabi (`pa`)** is now a complete language, prose included.

## 0.2.0 — 2026-11-15

- New `prashna.kp_horary(number=..., lat=..., lon=..., tz=..., date=..., time=...)`: the KP horary
  chart for a number from 1 to 249, cast for the moment and place of judgement. Returns the
  horary ascendant (the first degree of that number's part), the 12 Placidus cusps with star, sub
  and sub-sub lords and significators, the planets with KP lords and houses, planet significators,
  the KP 4-step chain and the ruling planets. Uses the Krishnamurti ayanamsa unless `ayanamsa` is
  sent. 30 credits. Same method as the Node.js SDK 0.13.0.
- `chart.kp_sublord` now also returns the KP ruling planets (`ruling_planets`), and
  `chart.kp_house_significator` returns each cusp's significator planets, the houses every planet
  signifies and the 4-step chain (new fields from the API; nothing removed).
- `chart.kp_sublord`'s `planet` and `chart.kp_house_significator`'s `cusp` are now optional. The
  API never read them: it always returns every planet and all 12 cusps. Code that passes them
  keeps working.
- 323 methods (322 endpoints).

## 0.1.0 — 2026-11-15

First release of the official Python SDK.

- `LifeAstro` (blocking) and `AsyncLifeAstro` (`asyncio`) clients on `httpx`, the only runtime
  dependency. Both are context managers and have `close()`. The API key comes from `api_key=`
  or the `LIFEASTRO_API_KEY` environment variable.
- 322 methods in 23 resource groups (`client.panchang.basic(...)`, `client.chart.planets(...)`,
  `client.western.natal.chart(...)`, ...): one method per endpoint, generated from the same
  manifest as the Node.js SDK 0.8.0, with the Node method and argument names in snake_case.
- Keyword arguments mapped to the API's wire names: unprefixed `date` / `time` / `tz` / `lat` /
  `lon` for a chart, `birth.*` for the natal chart of transit-style methods, `boy.*` / `girl.*`
  for kundli matching and `personA.*` / `personB.*` for Western pairs. Moment methods send
  today's date in the given `tz` when `date` is left out.
- `lang` on every Vedic method whose response carries names or text, sent as `lang` and
  `locale`. `Locale` lists the 10 codes: `en`, `hi`, `mr`, `gu`, `bn`, `te`, `ta`, `kn`, `ml`
  (complete) and `pa` (names and terms).
- Typed errors with `status`, `code`, `message` and `request_id`: `BadRequestError`,
  `AuthenticationError`, `PaymentRequiredError`, `PermissionDeniedError`, `NotFoundError`,
  `RateLimitError` (`retry_after`), `ServerError`, `LifeAstroConnectionError` and
  `LifeAstroTimeoutError`.
- Automatic retries with exponential backoff on 429, 5xx, network errors and timeouts,
  honouring `Retry-After`; per-call `request_options={"timeout": ..., "raw": ...}`.
- `on_response` hook, as a client argument and per call (`request_options={"on_response": ...}`):
  receives a `ResponseInfo` with the request id, `credits_remaining`, the rate limit
  (`RateLimit(limit, remaining, reset_at)`), the cache result and the answer's language for every
  call, success or error. Exported `ResponseInfo`, `RateLimit` and `ResponseHook`. See "Credits,
  rate limit and request id" in the README. Same as the Node SDK 0.10.0 `onResponse`.
- `client.request(path, query)` / `client.get(...)` to call any `/v1/*` endpoint directly.
- Responses are the parsed JSON (`dict` / `list`). Full type hints, `py.typed`, checked with
  `mypy --strict`. Every method's docstring has the endpoint description, credit cost and path.
