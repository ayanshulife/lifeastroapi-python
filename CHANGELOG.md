# Changelog

## 0.1.0 — 2026-11-14

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
- Not in this version: branded PDF rendering of `reports.*` (the Node SDK's `lifeastroapi/pdf`).
