"""Report JSON to branded HTML and to PDF bytes."""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Callable

from . import _js
from ._branding import template_branding
from ._chrome import ChromePdfEngine
from ._options import PdfEngine, PdfError, PdfOptions, check_cancelled
from ._outline import OutlineItem, add_pdf_outline, link_target_pages
from ._print_css import merge_margin, with_print_css
from ._threads import run_in_thread

# A report is the parsed JSON, exactly as ``client.reports.*`` returns it. The templates are
# imported inside each function, so that importing this module stays cheap.


def _render(
    template: Callable[..., Any], data: Mapping[str, Any], branding: Mapping[str, object] | None
) -> str:
    if not isinstance(data, Mapping):
        raise TypeError(
            "expected the report JSON (a dict) from client.reports, got "
            f"{type(data).__name__}. With AsyncLifeAstro, await the call first."
        )
    return str(template(data, template_branding(branding)))


def html_to_pdf(
    html: str,
    *,
    options: PdfOptions | None = None,
    engine: PdfEngine | None = None,
    cancel: threading.Event | None = None,
) -> bytes:
    """Print a complete HTML document to PDF bytes.

    :param engine: Default: a headless Chrome started for this one call. To make many
        PDFs, create one :class:`ChromePdfEngine` and pass it to every call.
    :param cancel: Set this event from another thread to stop the job.
    :raises PdfError: No browser, a browser or service failure, a timeout or a cancellation.
    """
    html = with_print_css(html, options)
    if engine is not None:
        return engine.html_to_pdf(html, options, cancel=cancel)
    with ChromePdfEngine() as own:
        return own.html_to_pdf(html, options, cancel=cancel)


async def html_to_pdf_async(
    html: str, *, options: PdfOptions | None = None, engine: PdfEngine | None = None
) -> bytes:
    """:func:`html_to_pdf` without blocking the event loop. Cancelling the task stops it."""
    return await run_in_thread(
        lambda stop: html_to_pdf(html, options=options, engine=engine, cancel=stop)
    )


def render_kundli_lite_html(
    data: Mapping[str, Any], branding: Mapping[str, object] | None = None
) -> str:
    """Vedic birth chart (lite) as a complete, branded HTML document.

    No browser, process, file or network access.

    :param data: The JSON from ``client.reports.kundli_lite(...)``.
    :param branding: Your :class:`Branding`.
    """
    from ._templates import kundli_lite

    return _render(kundli_lite.renderKundliLiteHtml, data, branding)


def kundli_lite_pdf(
    data: Mapping[str, Any],
    branding: Mapping[str, object] | None = None,
    *,
    options: PdfOptions | None = None,
    engine: PdfEngine | None = None,
    cancel: threading.Event | None = None,
) -> bytes:
    """Vedic birth chart (lite) as PDF bytes.

    :param data: The JSON from ``client.reports.kundli_lite(...)``.
    :param branding: Your :class:`Branding`.
    :param options: :class:`PdfOptions`.
    :param engine: Default: a headless Chrome started for this one call.
    :param cancel: Set this event from another thread to stop the job.
    """
    html = render_kundli_lite_html(data, branding)
    return html_to_pdf(html, options=options, engine=engine, cancel=cancel)


async def kundli_lite_pdf_async(
    data: Mapping[str, Any],
    branding: Mapping[str, object] | None = None,
    *,
    options: PdfOptions | None = None,
    engine: PdfEngine | None = None,
) -> bytes:
    """:func:`kundli_lite_pdf` without blocking the event loop. Cancelling the task stops it."""
    return await run_in_thread(
        lambda stop: kundli_lite_pdf(data, branding, options=options, engine=engine, cancel=stop)
    )


def render_kundli_detailed_html(
    data: Mapping[str, Any], branding: Mapping[str, object] | None = None
) -> str:
    """Detailed kundli as a complete, branded HTML document.

    No browser, process, file or network access.

    :param data: The JSON from ``client.reports.kundli_detailed(...)``.
    :param branding: Your :class:`Branding`.
    """
    from ._templates import kundli_detailed

    return _render(kundli_detailed.renderKundliDetailedHtml, data, branding)


def kundli_detailed_pdf(
    data: Mapping[str, Any],
    branding: Mapping[str, object] | None = None,
    *,
    options: PdfOptions | None = None,
    engine: PdfEngine | None = None,
    cancel: threading.Event | None = None,
) -> bytes:
    """Detailed kundli as PDF bytes.

    :param data: The JSON from ``client.reports.kundli_detailed(...)``.
    :param branding: Your :class:`Branding`.
    :param options: :class:`PdfOptions`.
    :param engine: Default: a headless Chrome started for this one call.
    :param cancel: Set this event from another thread to stop the job.
    """
    html = render_kundli_detailed_html(data, branding)
    return html_to_pdf(html, options=options, engine=engine, cancel=cancel)


async def kundli_detailed_pdf_async(
    data: Mapping[str, Any],
    branding: Mapping[str, object] | None = None,
    *,
    options: PdfOptions | None = None,
    engine: PdfEngine | None = None,
) -> bytes:
    """:func:`kundli_detailed_pdf` without blocking the event loop. Cancelling the task stops it."""
    return await run_in_thread(
        lambda stop: kundli_detailed_pdf(
            data, branding, options=options, engine=engine, cancel=stop
        )
    )


def render_kundli_brihad_html(
    data: Mapping[str, Any], branding: Mapping[str, object] | None = None
) -> str:
    """Brihad (comprehensive) kundli as a complete, branded HTML document.

    No browser, process, file or network access.

    :param data: The JSON from ``client.reports.kundli_brihad(...)``.
    :param branding: Your :class:`Branding`.
    """
    from ._templates import kundli_brihad

    return _render(kundli_brihad.renderKundliBrihadHtml, data, branding)


def kundli_brihad_pdf(
    data: Mapping[str, Any],
    branding: Mapping[str, object] | None = None,
    *,
    options: PdfOptions | None = None,
    engine: PdfEngine | None = None,
    cancel: threading.Event | None = None,
) -> bytes:
    """Brihad (comprehensive) kundli as PDF bytes.

    Adds a running header and footer, a table of contents with each section's real page,
    and bookmarks. It prints twice and runs to a few hundred pages, so make it in a
    background job.

    :param data: The JSON from ``client.reports.kundli_brihad(...)``.
    :param branding: Your :class:`Branding`.
    :param options: :class:`PdfOptions`.
    :param engine: Default: a headless Chrome started for this one call.
    :param cancel: Set this event from another thread to stop the job.
    """
    html = render_kundli_brihad_html(data, branding)
    check_cancelled(cancel)
    if engine is not None:
        return _print_brihad(html, data, branding, options, engine, cancel)
    with ChromePdfEngine() as own:
        return _print_brihad(html, data, branding, options, own, cancel)


async def kundli_brihad_pdf_async(
    data: Mapping[str, Any],
    branding: Mapping[str, object] | None = None,
    *,
    options: PdfOptions | None = None,
    engine: PdfEngine | None = None,
) -> bytes:
    """:func:`kundli_brihad_pdf` without blocking the event loop. Cancelling the task stops it."""
    return await run_in_thread(
        lambda stop: kundli_brihad_pdf(data, branding, options=options, engine=engine, cancel=stop)
    )


def render_match_making_html(
    data: Mapping[str, Any], branding: Mapping[str, object] | None = None
) -> str:
    """Match making (kundli milan) as a complete, branded HTML document.

    No browser, process, file or network access.

    :param data: The JSON from ``client.reports.match_making(...)``.
    :param branding: Your :class:`Branding`.
    """
    from ._templates import match_making

    return _render(match_making.renderMatchMakingHtml, data, branding)


def match_making_pdf(
    data: Mapping[str, Any],
    branding: Mapping[str, object] | None = None,
    *,
    options: PdfOptions | None = None,
    engine: PdfEngine | None = None,
    cancel: threading.Event | None = None,
) -> bytes:
    """Match making (kundli milan) as PDF bytes.

    :param data: The JSON from ``client.reports.match_making(...)``.
    :param branding: Your :class:`Branding`.
    :param options: :class:`PdfOptions`.
    :param engine: Default: a headless Chrome started for this one call.
    :param cancel: Set this event from another thread to stop the job.
    """
    html = render_match_making_html(data, branding)
    return html_to_pdf(html, options=options, engine=engine, cancel=cancel)


async def match_making_pdf_async(
    data: Mapping[str, Any],
    branding: Mapping[str, object] | None = None,
    *,
    options: PdfOptions | None = None,
    engine: PdfEngine | None = None,
) -> bytes:
    """:func:`match_making_pdf` without blocking the event loop. Cancelling the task stops it."""
    return await run_in_thread(
        lambda stop: match_making_pdf(data, branding, options=options, engine=engine, cancel=stop)
    )


def render_dasha_analysis_html(
    data: Mapping[str, Any], branding: Mapping[str, object] | None = None
) -> str:
    """Dasha analysis as a complete, branded HTML document.

    No browser, process, file or network access.

    :param data: The JSON from ``client.reports.dasha_analysis(...)``.
    :param branding: Your :class:`Branding`.
    """
    from ._templates import dasha_analysis

    return _render(dasha_analysis.renderDashaAnalysisHtml, data, branding)


def dasha_analysis_pdf(
    data: Mapping[str, Any],
    branding: Mapping[str, object] | None = None,
    *,
    options: PdfOptions | None = None,
    engine: PdfEngine | None = None,
    cancel: threading.Event | None = None,
) -> bytes:
    """Dasha analysis as PDF bytes.

    :param data: The JSON from ``client.reports.dasha_analysis(...)``.
    :param branding: Your :class:`Branding`.
    :param options: :class:`PdfOptions`.
    :param engine: Default: a headless Chrome started for this one call.
    :param cancel: Set this event from another thread to stop the job.
    """
    html = render_dasha_analysis_html(data, branding)
    return html_to_pdf(html, options=options, engine=engine, cancel=cancel)


async def dasha_analysis_pdf_async(
    data: Mapping[str, Any],
    branding: Mapping[str, object] | None = None,
    *,
    options: PdfOptions | None = None,
    engine: PdfEngine | None = None,
) -> bytes:
    """:func:`dasha_analysis_pdf` without blocking the event loop. Cancelling the task stops it."""
    return await run_in_thread(
        lambda stop: dasha_analysis_pdf(data, branding, options=options, engine=engine, cancel=stop)
    )


def render_numerology_html(
    data: Mapping[str, Any], branding: Mapping[str, object] | None = None
) -> str:
    """Numerology as a complete, branded HTML document.

    No browser, process, file or network access.

    :param data: The JSON from ``client.reports.numerology(...)``.
    :param branding: Your :class:`Branding`.
    """
    from ._templates import numerology

    return _render(numerology.renderNumerologyHtml, data, branding)


def numerology_pdf(
    data: Mapping[str, Any],
    branding: Mapping[str, object] | None = None,
    *,
    options: PdfOptions | None = None,
    engine: PdfEngine | None = None,
    cancel: threading.Event | None = None,
) -> bytes:
    """Numerology as PDF bytes.

    :param data: The JSON from ``client.reports.numerology(...)``.
    :param branding: Your :class:`Branding`.
    :param options: :class:`PdfOptions`.
    :param engine: Default: a headless Chrome started for this one call.
    :param cancel: Set this event from another thread to stop the job.
    """
    html = render_numerology_html(data, branding)
    return html_to_pdf(html, options=options, engine=engine, cancel=cancel)


async def numerology_pdf_async(
    data: Mapping[str, Any],
    branding: Mapping[str, object] | None = None,
    *,
    options: PdfOptions | None = None,
    engine: PdfEngine | None = None,
) -> bytes:
    """:func:`numerology_pdf` without blocking the event loop. Cancelling the task stops it."""
    return await run_in_thread(
        lambda stop: numerology_pdf(data, branding, options=options, engine=engine, cancel=stop)
    )


def render_sade_sati_html(
    data: Mapping[str, Any], branding: Mapping[str, object] | None = None
) -> str:
    """Sade Sati as a complete, branded HTML document.

    No browser, process, file or network access.

    :param data: The JSON from ``client.reports.sade_sati(...)``.
    :param branding: Your :class:`Branding`.
    """
    from ._templates import sade_sati

    return _render(sade_sati.renderSadeSatiHtml, data, branding)


def sade_sati_pdf(
    data: Mapping[str, Any],
    branding: Mapping[str, object] | None = None,
    *,
    options: PdfOptions | None = None,
    engine: PdfEngine | None = None,
    cancel: threading.Event | None = None,
) -> bytes:
    """Sade Sati as PDF bytes.

    :param data: The JSON from ``client.reports.sade_sati(...)``.
    :param branding: Your :class:`Branding`.
    :param options: :class:`PdfOptions`.
    :param engine: Default: a headless Chrome started for this one call.
    :param cancel: Set this event from another thread to stop the job.
    """
    html = render_sade_sati_html(data, branding)
    return html_to_pdf(html, options=options, engine=engine, cancel=cancel)


async def sade_sati_pdf_async(
    data: Mapping[str, Any],
    branding: Mapping[str, object] | None = None,
    *,
    options: PdfOptions | None = None,
    engine: PdfEngine | None = None,
) -> bytes:
    """:func:`sade_sati_pdf` without blocking the event loop. Cancelling the task stops it."""
    return await run_in_thread(
        lambda stop: sade_sati_pdf(data, branding, options=options, engine=engine, cancel=stop)
    )


def render_varshaphal_html(
    data: Mapping[str, Any], branding: Mapping[str, object] | None = None
) -> str:
    """Varshaphal (annual chart) as a complete, branded HTML document.

    No browser, process, file or network access.

    :param data: The JSON from ``client.reports.varshaphal(...)``.
    :param branding: Your :class:`Branding`.
    """
    from ._templates import varshaphal

    return _render(varshaphal.renderVarshaphalHtml, data, branding)


def varshaphal_pdf(
    data: Mapping[str, Any],
    branding: Mapping[str, object] | None = None,
    *,
    options: PdfOptions | None = None,
    engine: PdfEngine | None = None,
    cancel: threading.Event | None = None,
) -> bytes:
    """Varshaphal (annual chart) as PDF bytes.

    :param data: The JSON from ``client.reports.varshaphal(...)``.
    :param branding: Your :class:`Branding`.
    :param options: :class:`PdfOptions`.
    :param engine: Default: a headless Chrome started for this one call.
    :param cancel: Set this event from another thread to stop the job.
    """
    html = render_varshaphal_html(data, branding)
    return html_to_pdf(html, options=options, engine=engine, cancel=cancel)


async def varshaphal_pdf_async(
    data: Mapping[str, Any],
    branding: Mapping[str, object] | None = None,
    *,
    options: PdfOptions | None = None,
    engine: PdfEngine | None = None,
) -> bytes:
    """:func:`varshaphal_pdf` without blocking the event loop. Cancelling the task stops it."""
    return await run_in_thread(
        lambda stop: varshaphal_pdf(data, branding, options=options, engine=engine, cancel=stop)
    )


def render_horoscope_html(
    data: Mapping[str, Any], branding: Mapping[str, object] | None = None
) -> str:
    """Horoscope (daily, weekly or monthly) as a complete, branded HTML document.

    No browser, process, file or network access.

    :param data: The JSON from ``client.reports.horoscope_daily(...)``.
    :param branding: Your :class:`Branding`.
    """
    from ._templates import horoscope

    return _render(horoscope.renderHoroscopeHtml, data, branding)


def horoscope_pdf(
    data: Mapping[str, Any],
    branding: Mapping[str, object] | None = None,
    *,
    options: PdfOptions | None = None,
    engine: PdfEngine | None = None,
    cancel: threading.Event | None = None,
) -> bytes:
    """Horoscope (daily, weekly or monthly) as PDF bytes.

    :param data: The JSON from ``client.reports.horoscope_daily(...)``.
    :param branding: Your :class:`Branding`.
    :param options: :class:`PdfOptions`.
    :param engine: Default: a headless Chrome started for this one call.
    :param cancel: Set this event from another thread to stop the job.
    """
    html = render_horoscope_html(data, branding)
    return html_to_pdf(html, options=options, engine=engine, cancel=cancel)


async def horoscope_pdf_async(
    data: Mapping[str, Any],
    branding: Mapping[str, object] | None = None,
    *,
    options: PdfOptions | None = None,
    engine: PdfEngine | None = None,
) -> bytes:
    """:func:`horoscope_pdf` without blocking the event loop. Cancelling the task stops it."""
    return await run_in_thread(
        lambda stop: horoscope_pdf(data, branding, options=options, engine=engine, cancel=stop)
    )


def render_mangal_dosha_html(
    data: Mapping[str, Any], branding: Mapping[str, object] | None = None
) -> str:
    """Mangal Dosha (Manglik) as a complete, branded HTML document.

    No browser, process, file or network access.

    :param data: The JSON from ``client.reports.mangal_dosha(...)``.
    :param branding: Your :class:`Branding`.
    """
    from ._templates import mangal_dosha

    return _render(mangal_dosha.renderMangalDoshaHtml, data, branding)


def mangal_dosha_pdf(
    data: Mapping[str, Any],
    branding: Mapping[str, object] | None = None,
    *,
    options: PdfOptions | None = None,
    engine: PdfEngine | None = None,
    cancel: threading.Event | None = None,
) -> bytes:
    """Mangal Dosha (Manglik) as PDF bytes.

    :param data: The JSON from ``client.reports.mangal_dosha(...)``.
    :param branding: Your :class:`Branding`.
    :param options: :class:`PdfOptions`.
    :param engine: Default: a headless Chrome started for this one call.
    :param cancel: Set this event from another thread to stop the job.
    """
    html = render_mangal_dosha_html(data, branding)
    return html_to_pdf(html, options=options, engine=engine, cancel=cancel)


async def mangal_dosha_pdf_async(
    data: Mapping[str, Any],
    branding: Mapping[str, object] | None = None,
    *,
    options: PdfOptions | None = None,
    engine: PdfEngine | None = None,
) -> bytes:
    """:func:`mangal_dosha_pdf` without blocking the event loop. Cancelling the task stops it."""
    return await run_in_thread(
        lambda stop: mangal_dosha_pdf(data, branding, options=options, engine=engine, cancel=stop)
    )


# -- Brihad: header, footer, table of contents and bookmarks ----------------

#: Links on the section markers of the first print tell the page of every section. The
#: host cannot resolve, and the links are not in the PDF that is returned.
_MARKER_URL = "https://toc.lifeastroapi.invalid/T"
_MARKER = re.compile('<span style="color:#fff;font-size:1px;">\u27e6T([0-9]+)\u27e7</span>')
_MARKER_TOKEN = re.compile("⟦T[0-9]+⟧")


def _hide_markers(html: str) -> str:
    """For the last print: a no-break space keeps each marker's line box, without its text."""
    return _MARKER_TOKEN.sub("&nbsp;", html)


def _link_markers(html: str) -> str:
    return _MARKER.sub(
        '<span style="color:#fff;font-size:1px;"><a href="'
        + _MARKER_URL
        + '\\1" style="color:#fff;text-decoration:none;">\u27e6T\\1\u27e7</a></span>',
        html,
    )


def _insert_toc_after_cover(html: str, toc: str) -> str:
    end = html.find("</section>")
    if end < 0:
        return toc + html
    end += len("</section>")
    return f"{html[:end]}\n{toc}\n{html[end:]}"


def _print_brihad(
    html: str,
    data: Mapping[str, Any],
    branding: Mapping[str, object] | None,
    options: PdfOptions | None,
    engine: PdfEngine,
    cancel: threading.Event | None,
) -> bytes:
    from ._templates import kundli_brihad_sections as sections
    from ._templates import locales, shared

    options = options or PdfOptions()
    # Header and footer resolve branding as the pages do, so they need both brandings: the
    # palette depends on whether the caller or the report gave a colour.
    report, caller = data.get("Branding", _js.UNDEF), template_branding(branding)
    shown = options.display_header_footer
    options = replace(
        options,
        display_header_footer=True if shown is None else shown,
        header_template=options.header_template or sections.brihadHeaderTemplate(report, caller),
        footer_template=options.footer_template or sections.brihadFooterTemplate(report, caller),
        margin=merge_margin(sections.BRIHAD_PDF_MARGIN, options.margin),
    )

    def to_pdf(document: str) -> bytes:
        return engine.html_to_pdf(with_print_css(document, options), options, cancel=cancel)

    tagged = sections.tagBrihadSectionsForToc(html)
    titles: list[str] = tagged["titles"]
    if not titles:
        return to_pdf(html)
    locale = shared.safeLocale(data.get("Locale", _js.UNDEF))
    headings: dict[str, str] = locales.TOC_HEADING
    heading = headings.get(locale if isinstance(locale, str) else "en", headings["en"])

    def with_toc(body: str, entries: list[dict[str, Any]]) -> str:
        return _insert_toc_after_cover(body, str(sections.buildBrihadToc(entries, heading)))

    # Pass 1: a table of contents with the right number of rows, so it takes the same space.
    placeholder = [{"title": title, "page": i + 1} for i, title in enumerate(titles)]
    first = to_pdf(_link_markers(with_toc(tagged["html"], placeholder)))
    try:
        pages = link_target_pages(first)
    except PdfError:
        pages = {}
    entries: list[dict[str, Any]] = [
        {"title": title, "page": pages[f"{_MARKER_URL}{i}"]}
        for i, title in enumerate(titles)
        if f"{_MARKER_URL}{i}" in pages
    ]
    if not entries:
        return to_pdf(html)  # no table of contents rather than one with wrong numbers

    # Pass 2: the real page numbers, then the bookmarks from the same entries. Two sections
    # may start on one page (a short one lets the next follow), so numbers can repeat.
    final = to_pdf(with_toc(_hide_markers(tagged["html"]), entries))
    outline = [
        OutlineItem(
            entry["title"],
            entry["page"],
            1 if _js.test(locales.PART_PREFIX_RE, _js.trim(entry["title"])) else 2,
        )
        for entry in entries
    ]
    try:
        return add_pdf_outline(final, outline)
    except PdfError:
        return final  # a rewritten PDF (some Gotenberg setups) is returned without bookmarks
