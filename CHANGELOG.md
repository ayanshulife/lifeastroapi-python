# Changelog

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
