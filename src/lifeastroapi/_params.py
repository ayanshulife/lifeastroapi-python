"""Helpers used by the generated resource methods to build the query.

The wire names they write (``birth.lat``, ``boy.date``, ``start_date``, ...)
are the contract with the API and match the Node SDK's ``src/params.ts``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from urllib.parse import quote

from .types import QueryParams

_OFFSET = re.compile(r"^(?:UTC|GMT)?\s*([+-])(\d{1,2})(?::?(\d{2}))?$", re.IGNORECASE)


def put(query: QueryParams, key: str, value: Any) -> None:
    """Set ``key`` only when ``value`` is meaningful (skips ``None`` and ``""``)."""
    if value is None or value == "":
        return
    query[key] = value


#: The fields of a birth mapping (:class:`~lifeastroapi.types.BirthInput`).
BIRTH_FIELDS = ("date", "time", "tz", "lat", "lon")


def put_fields(
    query: QueryParams,
    value: Mapping[str, Any] | None,
    prefix: str,
    fields: tuple[str, ...] = BIRTH_FIELDS,
) -> None:
    """Copy fields of a birth mapping onto wire names: ``boy["date"]`` -> ``boy.date``."""
    if value is None:
        return
    for name in fields:
        put(query, prefix + name, value.get(name))


def build_path(template: str, values: Mapping[str, Any]) -> str:
    """Fill ``{name}`` placeholders in ``template``, percent-encoding each value."""
    path = template
    for name, value in values.items():
        if value is None or value == "":
            raise ValueError(f'Missing required path parameter "{name}" for {template}')
        path = path.replace("{" + name + "}", quote(_text(value), safe="!*'()"))
    return path


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e16:
        return str(int(value))
    return str(value)


def _zone(tz: str) -> tzinfo | None:
    match = _OFFSET.match(tz.strip())
    if match:
        sign, hours, minutes = match.groups()
        delta = timedelta(hours=int(hours), minutes=int(minutes or 0))
        return timezone(-delta if sign == "-" else delta)
    if tz.strip().upper() in ("UTC", "GMT", "Z"):
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(tz)
    except Exception:  # unknown zone, or no tz database on this machine
        return None


def today_in(tz: str | None, now: datetime | None = None) -> str:
    """Today's date (``YYYY-MM-DD``) in ``tz``.

    The API has no "today" default: every moment endpoint rejects a request
    without ``date``, so the SDK sends one. Falls back to the UTC date when
    ``tz`` cannot be resolved.
    """
    current = now if now is not None else datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    zone = _zone(tz) if tz else None
    return current.astimezone(zone or timezone.utc).strftime("%Y-%m-%d")
