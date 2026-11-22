"""Branded PDF reports, made on this machine from the report JSON.

    pip install lifeastroapi
    export LIFEASTRO_API_KEY=dv_live_...
    python examples/pdf_report.py

Needs Chrome, Chromium or Microsoft Edge (Debian / Ubuntu: apt-get install chromium
fonts-noto-core). The two report calls cost their credits; the PDFs cost nothing more.
Set LIFEASTRO_API_URL to call another server (for example a local one).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from lifeastroapi import AsyncLifeAstro, BirthInput
from lifeastroapi.pdf import Branding, ChromePdfEngine, kundli_lite_pdf_async, sade_sati_pdf_async

ARJUN: BirthInput = {
    "date": "1990-01-15",
    "time": "10:30",
    "tz": "Asia/Kolkata",
    "lat": 19.076,
    "lon": 72.8777,
}
BRANDING: Branding = {
    "company_name": "Acme Astro",
    "primary_color": "#6b21a8",
    "footer_text": "Acme Astro",
}


async def main() -> None:
    async with AsyncLifeAstro(base_url=os.environ.get("LIFEASTRO_API_URL")) as client:
        kundli, sade_sati = await asyncio.gather(
            client.reports.kundli_lite(**ARJUN, name="Arjun Mehta", place="Mumbai", lang="hi"),
            client.reports.sade_sati(**ARJUN, name="Arjun Mehta", place="Mumbai", lang="pa"),
        )
    # One browser for both; the event loop stays free while it prints.
    async with ChromePdfEngine() as engine:
        pdfs = await asyncio.gather(
            kundli_lite_pdf_async(kundli, BRANDING, engine=engine),
            sade_sati_pdf_async(sade_sati, BRANDING, engine=engine),
        )
    for name, data in zip(("kundli-hi.pdf", "sade-sati-pa.pdf"), pdfs):
        Path(name).write_bytes(data)
        print(f"{name}: {len(data)} bytes")


if __name__ == "__main__":
    asyncio.run(main())
