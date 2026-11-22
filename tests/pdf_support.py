"""Shared helpers of the PDF tests."""

from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import subprocess
from functools import cache
from pathlib import Path
from typing import Any, Callable, cast

import pytest

from lifeastroapi import pdf

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "pdf"
PDF_WORK = Path(
    os.environ.get("LIFEASTRO_PDF_WORK") or ROOT.parent / "LifeAstroAPI" / "pdf_work"
).resolve()

RENDERERS = (
    "KundliLite",
    "KundliDetailed",
    "KundliBrihad",
    "MatchMaking",
    "DashaAnalysis",
    "Numerology",
    "SadeSati",
    "Varshaphal",
    "Horoscope",
    "MangalDosha",
)
BRANDING: pdf.Branding = {
    "company_name": "Acme Astro",
    "logo_url": "https://cdn.example/acme/logo.png",
    "primary_color": "#6b21a8",
    "secondary_color": "#9333ea",
    "footer_text": "Acme Astro · confidential",
    "watermark_text": "SAMPLE",
}


def snake(name: str) -> str:
    return re.sub(r"(?<!^)([A-Z])", r"_\1", name).lower()


def renderer(name: str) -> Callable[..., str]:
    """``KundliLite`` -> ``pdf.render_kundli_lite_html``."""
    return cast("Callable[..., str]", getattr(pdf, f"render_{snake(name)}_html"))


def python_branding(branding: dict[str, str] | None) -> dict[str, str] | None:
    """The camelCase branding of the Node fixtures, with this SDK's keys."""
    return None if branding is None else {snake(key): value for key, value in branding.items()}


@cache
def fixture(name: str) -> Any:
    path = FIXTURES / f"{name}.json.gz"
    if not path.is_file():
        pytest.skip("tests/fixtures/pdf is in the git repository only, not in the sdist")
    return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))


def outline_titles(pdf_bytes: bytes) -> list[str]:
    """The bookmark titles as a PDF reader reads them."""
    titles = []
    for raw in re.findall(rb"/Title\s*\((\xfe\xff(?:\\.|[^\\)])*)\)", pdf_bytes, re.DOTALL):
        assert b"\r" not in raw and b"\n" not in raw, "a raw end of line changes the title"
        unescaped = re.sub(
            rb"\\(.)",
            lambda m: {b"r": b"\r", b"n": b"\n"}.get(m.group(1), m.group(1)),
            raw,
            flags=re.DOTALL,
        )
        titles.append(unescaped[2:].decode("utf-16-be"))
    return titles


def qpdf_outline_titles(path: Path) -> list[str]:
    """The bookmark titles as qpdf reads them. Skips without qpdf."""
    qpdf = shutil.which("qpdf")
    if qpdf is None:
        pytest.skip("qpdf is not installed")
    run = subprocess.run(
        [qpdf, "--json", "--json-key=outlines", str(path)], capture_output=True, check=True
    )
    found: list[str] = []

    def walk(items: list[dict[str, Any]]) -> None:
        for item in items:
            found.append(item["title"])
            walk(item["kids"])

    walk(json.loads(run.stdout)["outlines"])
    return found


def example(name: str, locale: str) -> dict[str, Any]:
    """The last example report of a renderer in a language (the fullest one)."""
    found = [
        case["data"]
        for case in fixture("cases")
        if case["fn"] == f"render{name}Html"
        and not case["branding"]
        and case["data"].get("Locale") == locale
    ]
    assert found, f"no {name} case in {locale}"
    return cast("dict[str, Any]", found[-1])
