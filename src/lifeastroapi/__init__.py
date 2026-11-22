"""Official Python SDK for LifeAstroAPI: Vedic astrology and the Hindu calendar.

    from lifeastroapi import LifeAstro

    client = LifeAstro(api_key="dv_live_...")  # or set LIFEASTRO_API_KEY
    day = client.panchang.basic(lat=23.0225, lon=72.5714, tz="Asia/Kolkata", lang="gu")

Branded PDF reports, made on your own machine: :mod:`lifeastroapi.pdf`.

Docs: https://lifeastroapi.com/docs/
"""

from ._client import API_KEY_ENV, DEFAULT_BASE_URL, AsyncLifeAstro, LifeAstro
from ._version import __version__
from .errors import (
    AuthenticationError,
    BadRequestError,
    LifeAstroConnectionError,
    LifeAstroError,
    LifeAstroTimeoutError,
    NotFoundError,
    PaymentRequiredError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
)
from .types import (
    LOCALES,
    Ayanamsa,
    BirthInput,
    HouseSystem,
    Locale,
    NatalWindowBirth,
    QueryParams,
    QueryValue,
    RateLimit,
    RequestOptions,
    ResponseHook,
    ResponseInfo,
)

__all__ = [
    "API_KEY_ENV",
    "DEFAULT_BASE_URL",
    "LOCALES",
    "AsyncLifeAstro",
    "AuthenticationError",
    "Ayanamsa",
    "BadRequestError",
    "BirthInput",
    "HouseSystem",
    "LifeAstro",
    "LifeAstroConnectionError",
    "LifeAstroError",
    "LifeAstroTimeoutError",
    "Locale",
    "NatalWindowBirth",
    "NotFoundError",
    "PaymentRequiredError",
    "PermissionDeniedError",
    "QueryParams",
    "QueryValue",
    "RateLimit",
    "RateLimitError",
    "RequestOptions",
    "ResponseHook",
    "ResponseInfo",
    "ServerError",
    "__version__",
]
