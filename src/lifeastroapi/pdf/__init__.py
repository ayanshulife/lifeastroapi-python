"""Branded PDF reports, made on your own machine from the JSON of ``client.reports``.

    from lifeastroapi import LifeAstro
    from lifeastroapi.pdf import kundli_lite_pdf

    report = LifeAstro().reports.kundli_lite(**arjun, lang="hi")
    pdf = kundli_lite_pdf(report, {"company_name": "Acme Astro"})

- ``render_*_html`` turns the JSON into HTML in pure Python: no browser, process, file or
  network access. Byte-identical to the Node SDK's ``lifeastroapi/pdf-html``.
- ``*_pdf`` prints that HTML with a Chrome, Chromium or Microsoft Edge on your machine, or
  with a Gotenberg service you run. ``*_pdf_async`` does it without blocking the event loop.

Nothing is sent to LifeAstroAPI for this.
"""

from __future__ import annotations

from typing import Final, TypedDict

from ._branding import Branding, clean_narrative, esc, esc_body, humanize, resolve_branding
from ._browser import find_browser
from ._chrome import ChromePdfEngine
from ._gotenberg import GotenbergPdfEngine
from ._options import PaperFormat, PdfEngine, PdfError, PdfMargin, PdfOptions
from ._outline import OutlineItem, add_pdf_outline
from ._reports import (
    dasha_analysis_pdf,
    dasha_analysis_pdf_async,
    horoscope_pdf,
    horoscope_pdf_async,
    html_to_pdf,
    html_to_pdf_async,
    kundli_brihad_pdf,
    kundli_brihad_pdf_async,
    kundli_detailed_pdf,
    kundli_detailed_pdf_async,
    kundli_lite_pdf,
    kundli_lite_pdf_async,
    mangal_dosha_pdf,
    mangal_dosha_pdf_async,
    match_making_pdf,
    match_making_pdf_async,
    numerology_pdf,
    numerology_pdf_async,
    render_dasha_analysis_html,
    render_horoscope_html,
    render_kundli_brihad_html,
    render_kundli_detailed_html,
    render_kundli_lite_html,
    render_mangal_dosha_html,
    render_match_making_html,
    render_numerology_html,
    render_sade_sati_html,
    render_varshaphal_html,
    sade_sati_pdf,
    sade_sati_pdf_async,
    varshaphal_pdf,
    varshaphal_pdf_async,
)


class PrintMargins(TypedDict):
    top: int
    right: int
    bottom: int
    left: int


class PrintOptions(TypedDict):
    width: int
    height: int
    margins: PrintMargins


#: A4 and the reports' page margins in points (1/72 inch), for print APIs that ignore the
#: CSS ``@page`` rule of the HTML (the same values as the Node SDK's ``A4_PRINT_OPTIONS``).
A4_PRINT_OPTIONS: Final[PrintOptions] = {
    "width": 595,
    "height": 842,
    "margins": {"top": 51, "right": 43, "bottom": 62, "left": 43},
}

__all__ = [
    "A4_PRINT_OPTIONS",
    "Branding",
    "ChromePdfEngine",
    "GotenbergPdfEngine",
    "OutlineItem",
    "PaperFormat",
    "PdfEngine",
    "PdfError",
    "PdfMargin",
    "PdfOptions",
    "PrintMargins",
    "PrintOptions",
    "add_pdf_outline",
    "clean_narrative",
    "dasha_analysis_pdf",
    "dasha_analysis_pdf_async",
    "esc",
    "esc_body",
    "find_browser",
    "horoscope_pdf",
    "horoscope_pdf_async",
    "html_to_pdf",
    "html_to_pdf_async",
    "humanize",
    "kundli_brihad_pdf",
    "kundli_brihad_pdf_async",
    "kundli_detailed_pdf",
    "kundli_detailed_pdf_async",
    "kundli_lite_pdf",
    "kundli_lite_pdf_async",
    "mangal_dosha_pdf",
    "mangal_dosha_pdf_async",
    "match_making_pdf",
    "match_making_pdf_async",
    "numerology_pdf",
    "numerology_pdf_async",
    "render_dasha_analysis_html",
    "render_horoscope_html",
    "render_kundli_brihad_html",
    "render_kundli_detailed_html",
    "render_kundli_lite_html",
    "render_mangal_dosha_html",
    "render_match_making_html",
    "render_numerology_html",
    "render_sade_sati_html",
    "render_varshaphal_html",
    "resolve_branding",
    "sade_sati_pdf",
    "sade_sati_pdf_async",
    "varshaphal_pdf",
    "varshaphal_pdf_async",
]
