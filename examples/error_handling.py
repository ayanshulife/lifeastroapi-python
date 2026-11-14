"""Typed errors, per-call options and the escape hatch.

    export LIFEASTRO_API_KEY=dv_live_...
    python examples/error_handling.py

Set LIFEASTRO_API_URL to call another server (for example a local one).
"""

from __future__ import annotations

import os

from lifeastroapi import (
    BadRequestError,
    LifeAstro,
    LifeAstroConnectionError,
    LifeAstroError,
    NotFoundError,
    PaymentRequiredError,
    RateLimitError,
)


def main() -> None:
    client = LifeAstro(base_url=os.environ.get("LIFEASTRO_API_URL"), max_retries=2)
    try:
        # An unknown remedy id: the API answers 404.
        client.remedies.mantra(id="no_such_mantra", lang="hi")
    except NotFoundError as err:
        print("Not found:", err.code, "| request id:", err.request_id)

    try:
        # A latitude out of range: 400.
        client.panchang.tithi(lat=123.0, lon=72.8777, tz="Asia/Kolkata", date="2027-01-15")
    except BadRequestError as err:
        print("Bad request:", err.message)

    try:
        # Per-call options: a shorter timeout for this call only.
        tithi = client.panchang.tithi(
            lat=19.076, lon=72.8777, tz="Asia/Kolkata", request_options={"timeout": 10}
        )
        print("Tithi today in Mumbai:", tithi["name"])
    except PaymentRequiredError:
        print("Out of credits for this key.")
    except RateLimitError as err:
        print(f"Rate limited; retry after {err.retry_after}s")
    except LifeAstroConnectionError as err:
        print("Network problem or timeout:", err.code)
    except LifeAstroError as err:
        print("API error:", err)

    # Escape hatch: any /v1 endpoint by its path and wire parameter names.
    version = client.request("/v1/meta/version")
    print("API version:", version)
    client.close()


if __name__ == "__main__":
    main()
