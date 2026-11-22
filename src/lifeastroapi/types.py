"""Shared input and option types, and the :class:`ResponseInfo` passed to ``on_response``.

Responses are returned as parsed JSON (``dict`` / ``list``) and typed ``Any``:
the API has hundreds of response shapes and they evolve on their own schedule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Literal, TypedDict, Union

#: Response language, passed as ``lang`` on Vedic methods.
#:
#: - Complete: ``en`` (default), ``hi``, ``mr``, ``gu``, ``bn``, ``te``, ``ta``, ``kn``, ``ml``,
#:   ``pa``.
#:   Names, terms and prose come back in the language.
#:
#: Ids, dates, numbers and explicit ``*_en`` / ``*_hi`` fields stay as they are in
#: every language. Western, tarot, geo and meta methods answer in English.
Locale = Literal["en", "hi", "mr", "gu", "bn", "te", "ta", "kn", "ml", "pa"]

#: Every value of :data:`Locale`, in the order of the README table.
LOCALES: tuple[Locale, ...] = ("en", "hi", "mr", "gu", "bn", "te", "ta", "kn", "ml", "pa")

#: Sidereal ayanamsa systems supported by the API (``lahiri`` is the default).
Ayanamsa = Literal["lahiri", "krishnamurti", "raman", "fagan", "yukteshwar", "true_chitrapaksha"]

#: House systems supported by the API. ``"whole-sign"`` is the spelling of SDK 0.2.0 and
#: earlier, which the API reads as ``"whole_sign"``.
HouseSystem = Literal[
    "whole_sign", "whole-sign", "equal", "placidus", "koch", "porphyry", "campanus", "regiomontanus"
]


class BirthInput(TypedDict):
    """A birth (or event) moment at a place.

    Used for ``boy`` / ``girl`` (kundli matching), ``person_a`` / ``person_b``
    (Western pairs) and ``birth`` (natal chart + transit moment).
    """

    date: str
    """ISO date, ``YYYY-MM-DD``."""
    time: str
    """24-hour time, ``HH:MM``."""
    tz: str
    """IANA name (``Asia/Kolkata``) or fixed offset (``+05:30``)."""
    lat: float
    """Latitude in decimal degrees, north positive."""
    lon: float
    """Longitude in decimal degrees, east positive."""


class _NatalWindowBirthRequired(TypedDict):
    date: str
    time: str
    tz: str


class NatalWindowBirth(_NatalWindowBirthRequired, total=False):
    """Natal chart for the window endpoints (``transit.windows``, ``transit.sade_sati_windows``).

    Only ``date``, ``time`` and ``tz`` are needed for the natal Moon; ``lat`` and
    ``lon`` add the lagna-based fields where an endpoint has them.
    """

    lat: float
    lon: float


@dataclass(frozen=True)
class RateLimit:
    """Your plan's per-minute rate limit, from the ``X-RateLimit-*`` headers."""

    limit: int
    """``X-RateLimit-Limit``: requests per minute for your plan."""
    remaining: int
    """``X-RateLimit-Remaining``: requests left in the current window."""
    reset_at: datetime
    """``X-RateLimit-Reset``: when the window resets (timezone-aware, UTC)."""


@dataclass(frozen=True)
class ResponseInfo:
    """What the API reported about one call besides its body.

    Passed to ``on_response`` (client argument or per call) for every final HTTP
    response, success or error; not for network failures or for attempts that were
    retried. A field is ``None`` when the API did not send its header.
    """

    status: int
    """HTTP status of the response."""
    path: str
    """Request path, e.g. ``/v1/panchang/basic``."""
    request_id: str | None = None
    """``X-Request-ID``. Quote it to support."""
    credits_remaining: int | None = None
    """``X-Credits-Remaining``: the balance after this call (unchanged after a failed call).
    ``None`` on free-tier accounts, whose allowance is not a balance, and on calls that cost
    nothing."""
    rate_limit: RateLimit | None = None
    """``X-RateLimit-*``: set only when all three headers are present and numeric."""
    cache: str | None = None
    """``X-Cache``, e.g. ``HIT`` when the API answered from its cache (billed the same)."""
    language: str | None = None
    """``Content-Language``: the language the answer is in."""


#: Receives the :class:`ResponseInfo` of each call. Exceptions raised inside it are ignored.
ResponseHook = Callable[[ResponseInfo], None]


class RequestOptions(TypedDict, total=False):
    """Per-call options, passed as ``request_options=`` to any method."""

    timeout: float
    """Override the client timeout for this call, in seconds."""
    raw: bool
    """Return the body exactly as received, without unwrapping a ``{data, meta}`` envelope."""
    on_response: ResponseHook
    """Called with this call's :class:`ResponseInfo` (after the client-level ``on_response``)."""


#: A query value. ``None`` and ``""`` are left out of the request.
QueryValue = Union[str, int, float, bool, None]
#: Query parameters by wire name (``birth.date``, ``boy.lat``, ``start_date``, ...).
QueryParams = dict[str, QueryValue]
