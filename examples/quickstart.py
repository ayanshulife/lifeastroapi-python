"""Quick start: today's panchang in Gujarati, a birth chart and a kundli match.

    pip install lifeastroapi
    export LIFEASTRO_API_KEY=dv_live_...
    python examples/quickstart.py

Set LIFEASTRO_API_URL to call another server (for example a local one).
"""

from __future__ import annotations

import os

from lifeastroapi import BirthInput, LifeAstro

ARJUN: BirthInput = {
    "date": "1990-01-15",
    "time": "10:30",
    "tz": "Asia/Kolkata",
    "lat": 19.076,
    "lon": 72.8777,
}
PRIYA: BirthInput = {
    "date": "1992-03-20",
    "time": "08:15",
    "tz": "Asia/Kolkata",
    "lat": 28.6139,
    "lon": 77.209,
}


def main() -> None:
    with LifeAstro(base_url=os.environ.get("LIFEASTRO_API_URL")) as client:
        # 1. Today's panchang for Ahmedabad, in Gujarati.
        day = client.panchang.basic(lat=23.0225, lon=72.5714, tz="Asia/Kolkata", lang="gu")
        print("Tithi:", day["tithi"]["name"], day["tithi"]["paksha"])
        print("Nakshatra:", day["nakshatra"]["name"], "| Vara:", day["vara"]["weekday"])
        print("Sunrise:", day["sunrise_local"], "| Sunset:", day["sunset_local"])

        # 2. A birth chart (unprefixed date / time / tz / lat / lon).
        chart = client.chart.planets(**ARJUN)
        for planet in chart["planets"]:
            print(f"{planet['name']:8} house {planet['house']:2}  {planet['dms_in_sign']}")

        # 3. Kundli matching (boy.* / girl.* on the wire).
        match = client.milan.ashtakoota_total(boy=ARJUN, girl=PRIYA)
        print("Guna milan:", match["total"], "/", match["max"], match["verdict"])


if __name__ == "__main__":
    main()
