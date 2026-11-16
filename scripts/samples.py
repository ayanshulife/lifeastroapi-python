"""Sample inputs for every SDK method, for the live sweep and the tests.

A port of the sample tables in the Node SDK's ``scripts/live-sweep.mjs``: the
values are written with the Node input field names (``startDate``, ``boy``,
``onDate``) and turned into Python keyword arguments through
``scripts/manifest.json``. The neutral sample person is Arjun Mehta, born
1990-01-15 10:30 in Mumbai.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Callable

MANIFEST = Path(__file__).resolve().parent / "manifest.json"

A: dict[str, Any] = {
    "lat": 19.076,
    "lon": 72.8777,
    "date": "1990-01-15",
    "time": "10:30",
    "tz": "Asia/Kolkata",
}
B: dict[str, Any] = {
    "lat": 28.6139,
    "lon": 77.209,
    "date": "1992-06-20",
    "time": "14:15",
    "tz": "Asia/Kolkata",
}
NOW: dict[str, Any] = {
    "lat": 19.076,
    "lon": 72.8777,
    "tz": "Asia/Kolkata",
    "date": "2026-11-20",
    "time": "12:00",
}

#: Sample input for each base shape (Node field names).
SHAPE_INPUT: dict[str, Callable[[], dict[str, Any]]] = {
    "moment": lambda: {**NOW},
    "birth": lambda: {**A},
    "birthPrefixed": lambda: {**A},
    "boygirl": lambda: {"boy": {**A}, "girl": {**B}},
    "twoPerson": lambda: {"personA": {**A}, "personB": {**B}},
    "rashi": lambda: {"rashi": "Aries"},
    "numerology": lambda: {"name": "Arjun Mehta", "dob": "1990-01-15"},
    "dateRange": lambda: {"startDate": "2026-01-01", "endDate": "2027-12-31"},
    "westernNatal": lambda: {**A},
    "westernMoment": lambda: {"date": NOW["date"], "time": NOW["time"], "tz": NOW["tz"]},
    "muhurta": lambda: {
        "lat": NOW["lat"],
        "lon": NOW["lon"],
        "tz": NOW["tz"],
        "startDate": "2026-11-01",
        "endDate": "2026-11-30",
    },
    "natalTransit": lambda: {
        "birth": {**A},
        "date": NOW["date"],
        "time": NOW["time"],
        "tz": NOW["tz"],
    },
    "natalTransitPlace": lambda: {
        "birth": {**A},
        "date": NOW["date"],
        "time": NOW["time"],
        "tz": NOW["tz"],
    },
    "natalWindow": lambda: {"birth": {**A}, "from": NOW["date"], "tz": NOW["tz"]},
    "natalWindowOptional": lambda: {"birth": {**A}, "from": NOW["date"], "tz": NOW["tz"]},
    # Deliberately empty: exercises the SDK's "today" + UTC defaults.
    "instant": lambda: {},
    "none": lambda: {},
    "custom": lambda: {},
}

#: Sample values for required extras, keyed by wire name.
WIRE: dict[str, Any] = {
    "age_in_years": 35.5,
    "asc_sign": "leo",
    "asc_lon": 123.4,
    "aspect": "trine",
    "kind": "trine",
    "birth.date": A["date"],
    "birth.time": A["time"],
    "birth.tz": A["tz"],
    "birth_date": A["date"],
    "birth_nak": 7,
    "birth_moon_sign": 3,
    "boy.date": A["date"],
    "boy.time": A["time"],
    "boy.tz": A["tz"],
    "girl.date": B["date"],
    "girl.time": B["time"],
    "girl.tz": B["tz"],
    "cusp": 7,
    "date": NOW["date"],
    "time": NOW["time"],
    "tz": NOW["tz"],
    "decan": 2,
    "degree": 100,
    "dob": A["date"],
    "start_date": "2026-01-01",
    "end_date": "2027-12-31",
    "from": "2026-06-01T00:00:00Z",
    "to": "2027-01-01T00:00:00Z",
    "house": 5,
    "lat": A["lat"],
    "lon": A["lon"],
    "lord": "Jupiter",
    "lot_sign": "cancer",
    "maha": "Jupiter",
    "month": 11,
    "name": "Arjun Mehta",
    "number": 23,
    "natal_planet": "Sun",
    "transit_planet": "Saturn",
    "observer_lat": B["lat"],
    "observer_lon": B["lon"],
    "planet": "Jupiter",
    "planet_a": "Sun",
    "planet_b": "Moon",
    "q": "Mumbai",
    "return_year": 2026,
    "sign": "Leo",
    "sign_a": "Aries",
    "sign_b": "Leo",
    "type": "three",
    "week": "2026-W47",
    "week_start": "2026-11-16",
    "year": 2026,
    "year_month": "2026-11",
}

#: Sample values for path parameters, keyed by name.
PATH: dict[str, Any] = {
    "md": "Jupiter",
    "ad": "Saturn",
    "pd": "Mercury",
    "sd": "Ketu",
    "component": "sthana",
    "house": "8",
    "koota": "nadi",
    "n": 5,
    "name": "Jupiter",
    "number": 1,
    "planet": "Jupiter",
    "star": "Regulus",
    "varga": "D9",
}

#: Per-path corrections where a generic sample is wrong for that endpoint
#: (Node field names), merged over the generated input.
PER_PATH: dict[str, dict[str, Any]] = {
    "/v1/dasha/char/{md}": {"md": "leo"},
    "/v1/dasha/char/{md}/{ad}": {"md": "leo", "ad": "scorpio"},
    "/v1/dasha/yogini/{name}": {"name": "mangala"},
    "/v1/western/natal/planet/{name}": {"name": "Venus"},
    "/v1/western/natal/lot/{name}": {"name": "fortune"},
    "/v1/western/natal/fixed-stars/{name}": {"name": "Regulus"},
    "/v1/western/retrograde-window/{planet}": {"planet": "Mercury"},
    "/v1/vedic/remedies/lal-kitab/{planet}/{house}": {"planet": "saturn", "house": "8"},
    "/v1/geo/place/{id}": {"id": "1275339"},
    "/v1/vedic/narrative/yoga/{id}": {"id": "hamsa"},
    "/v1/vedic/narrative/dosha/{id}": {"id": "mangal_dosha"},
    "/v1/vedic/remedies/{id}": {"id": "hanuman_chalisa"},
    "/v1/vedic/remedies/mantra/{id}": {"id": "hanuman_chalisa"},
    "/v1/vedic/remedies/daan/{id}": {"id": "sadesati_setting_shanti"},
    "/v1/vedic/remedies/vrat/{id}": {"id": "kaalsarp_dosha_shanti"},
    "/v1/vedic/remedies/pooja/{id}": {"id": "jupiter_dasha_shanti"},
    "/v1/vedic/remedies/yantra/{id}": {"id": "vedic.L1.remedy.yantra.jupiter"},
    "/v1/vedic/remedies/rudraksha/{id}": {"id": "vedic.L1.remedy.rudraksha.jupiter"},
    "/v1/tarot/card/{id}": {"id": "5"},
    "/v1/vedic/narrative/prashna": {"topic": "career"},
    "/v1/transit/windows": {"planet": "saturn"},
    "/v1/vedic/remedies/for-graha": {"graha": "saturn", "reason": "debilitated"},
    "/v1/milan/dasha-sync": {"marriageWindows": True, "from": NOW["date"], "years": 3},
    "/v1/panchang/monthly": {"tzOffsetHours": 5.5},
    "/v1/horoscope/monthly": {"month": "2026-11"},
    "/v1/reports/horoscope/monthly": {"month": "2026-11"},
    "/v1/western/dignities/receptions": {
        "sun": 294.78,
        "moon": 152.4,
        "venus": 300.1,
        "mars": 250.2,
    },
    "/v1/muhurta/naamkaran": {"birthDate": "2026-11-05"},
    "/v1/western/transits/calendar": {"from": "2026-11-01", "to": "2026-11-20"},
    "/v1/western/transits/exact": {"from": "2026-01-01T00:00:00Z", "to": "2027-01-01T00:00:00Z"},
    "/v1/vedic/narrative/reference/{family}": {"family": "yoga"},
    "/v1/chart/ashtakvarga/{planet}": {"planet": "Jupiter"},
    # Not in the Node sweep's table: the generic "type" sample ("three", a tarot
    # spread) is not a vrat family.
    "/v1/festivals/vrat": {"type": "ekadashi"},
}


def load_manifest() -> list[dict[str, Any]]:
    """The resolved manifest written by ``scripts/generate.py``."""
    entries: list[dict[str, Any]] = json.loads(MANIFEST.read_text())
    return entries


def has_param(entry: dict[str, Any], name: str) -> bool:
    return any(p["name"] == name for p in entry["params"])


def build_kwargs(entry: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Keyword arguments for one manifest entry, and the samples that are missing."""
    node_input = SHAPE_INPUT[entry["shape"]]()
    missing: list[str] = []
    for name in entry["pathParams"]:
        if name in PATH:
            node_input[name] = PATH[name]
        else:
            missing.append(f"path:{name}")
    for extra in entry["extras"]:
        if not extra["required"]:
            continue
        if extra["wire"] in WIRE:
            node_input[extra["field"]] = WIRE[extra["wire"]]
        else:
            missing.append(f"extra:{extra['wire']}")
    node_input.update(PER_PATH.get(entry["path"], {}))
    missing = [
        m for m in missing if not (m.startswith("path:") and node_input.get(m[5:]) is not None)
    ]
    kwargs = {p["name"]: node_input[p["node"]] for p in entry["params"] if p["node"] in node_input}
    return kwargs, missing


def resolve_method(client: Any, entry: dict[str, Any]) -> Callable[..., Any] | None:
    """The bound SDK method of a manifest entry (``western.solar_arc.directions`` ...)."""
    target: Any = client
    for part in entry["py"].split("."):
        target = getattr(target, part, None)
    return target if callable(target) else None


def iter_entries(
    skip: list[str] | None = None, only: list[str] | None = None
) -> Iterator[dict[str, Any]]:
    for entry in load_manifest():
        if skip and any(entry["path"].startswith(p) for p in skip):
            continue
        if only and not any(s in entry["path"] for s in only):
            continue
        yield entry
