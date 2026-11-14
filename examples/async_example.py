"""Async client: several calls at once with asyncio.gather.

    export LIFEASTRO_API_KEY=dv_live_...
    python examples/async_example.py

Set LIFEASTRO_API_URL to call another server (for example a local one).
"""

from __future__ import annotations

import asyncio
import os

from lifeastroapi import AsyncLifeAstro, BirthInput

ARJUN: BirthInput = {
    "date": "1990-01-15",
    "time": "10:30",
    "tz": "Asia/Kolkata",
    "lat": 19.076,
    "lon": 72.8777,
}


async def main() -> None:
    async with AsyncLifeAstro(base_url=os.environ.get("LIFEASTRO_API_URL")) as client:
        # Three calls in parallel, all answered in Bengali.
        kolkata, dasha, festivals = await asyncio.gather(
            client.panchang.basic(lat=22.5726, lon=88.3639, tz="Asia/Kolkata", lang="bn"),
            client.dasha.vimshottari_current(**ARJUN, lang="bn"),
            client.festivals.month(year=2027, month=1, lat=22.5726, lon=88.3639, lang="bn"),
        )
    print("Kolkata tithi:", kolkata["tithi"]["name"], kolkata["tithi"]["paksha"])
    print("Mahadasha:", dasha["maha"]["lord"], "| Antardasha:", dasha["antar"]["lord"])
    for festival in festivals["festivals"][:5]:
        print(festival["date"], festival["name"], f"({festival['name_en']})")


if __name__ == "__main__":
    asyncio.run(main())
