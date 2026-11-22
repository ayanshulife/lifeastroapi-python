"""Every Branding field and print option reaches the paper.

The vectors come from the Node SDK (``scripts/pdf_goldens.mjs``, options.json.gz). The HTML
itself is covered by the parity tests; this covers what parity does not exercise, and the
hand-written print options and Brihad wrapper.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import re
import shutil
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Callable

import pytest

from lifeastroapi import pdf
from lifeastroapi.pdf import _js, _print_css, _reports
from lifeastroapi.pdf._outline import page_count
from lifeastroapi.pdf._templates import colors, locales, planet_glyphs, shared
from lifeastroapi.pdf._templates import kundli_brihad_sections as sections

from pdf_devtools_stub import DevToolsStub
from pdf_support import RENDERERS, example, fixture, python_branding, renderer, snake

LANGUAGES = ("en", "hi", "mr", "te", "ta", "kn", "ml", "gu", "bn", "pa")
API_DEFAULTS = {
    "CompanyName": "",
    "LogoURL": "",
    "PrimaryColor": "#1a1a1a",
    "SecondaryColor": "#666666",
    "FooterText": "Generated using LifeAstroAPI",
    "WatermarkText": "",
}
PROPERTY_NAMES = (
    "constructor",
    "toString",
    "__proto__",
    "valueOf",
    "hasOwnProperty",
    "isPrototypeOf",
)
MARKER = "https://toc.lifeastroapi.invalid/T"


def or_undefined(value: Any) -> Any:
    return _js.UNDEF if value is None else value


def brihad(data: dict[str, Any], branding: dict[str, str] | None = None) -> str:
    return pdf.render_kundli_brihad_html(data, branding)


class Recorder:
    """An engine that keeps what it was given and prints a small PDF with the marker links."""

    def __init__(self, sections_per_page: int = 1) -> None:
        self.html: list[str] = []
        self.options: list[pdf.PdfOptions] = []
        self._per_page = sections_per_page

    def html_to_pdf(
        self,
        html: str,
        options: pdf.PdfOptions | None = None,
        *,
        cancel: threading.Event | None = None,
    ) -> bytes:
        self.html.append(html)
        self.options.append(options or pdf.PdfOptions())
        count = len(re.findall(f'<a href="{re.escape(MARKER)}[0-9]+"', html))
        pages: list[list[int]] = [[], []] + [
            list(range(first, min(first + self._per_page, count)))
            for first in range(0, count, self._per_page)
        ]
        out = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        for number, links in enumerate(pages):
            refs = b" ".join(b"%d 0 R" % (1000 + link) for link in links)
            body = b"<< /Type /Page /Annots [%s] >>" % refs
            out += b"%d 0 obj\n%s\nendobj\n" % (10 + number, body)
            for link in links:
                uri = f"{MARKER}{link}".encode()
                action = b"<< /Subtype /Link /A << /S /URI /URI (%s) >> >>" % uri
                out += b"%d 0 obj\n%s\nendobj\n" % (1000 + link, action)
        return out + b"trailer\n<< /Root 1 0 R >>\nstartxref\n0\n%%EOF\n"


def printed_brihad(
    data: dict[str, Any],
    branding: dict[str, str] | None = None,
    options: pdf.PdfOptions | None = None,
) -> Recorder:
    engine = Recorder()
    pdf.kundli_brihad_pdf(data, branding, options=options, engine=engine)
    return engine


# -- colours -----------------------------------------------------------------


def test_colours_match_node() -> None:
    for row in fixture("options")["colours"]:
        value, rgb = row["value"], colors.parseColor(row["value"])
        assert (None if rgb is _js.UNDEF else rgb) == row["rgb"], ascii(value)
        assert colors.printableColor(value, "#1a1a1a") == row["printable"], ascii(value)
        if "dark" in row:
            assert colors.toHex(colors.darkenToContrast(rgb, 5.2)) == row["dark"], value
            assert colors.toHex(colors.tintOnWhite(rgb, 5)) == row["tint"], value
            assert colors.seeThrough(rgb) == row["fill"], value


@pytest.mark.parametrize(
    ("value", "rgb"),
    [
        ("#0B5CAD", [11, 92, 173]),
        ("#05a", [0, 85, 170]),  # `$&$&` doubles each digit
        ("#05af", [0, 85, 170]),
        ("#0b5cadff", [11, 92, 173]),
        ("RebeccaPurple", [102, 51, 153]),
        ("INDIGO", [75, 0, 130]),  # lower case without the culture (Turkish has a dotless i)
        ("rgb(11, 92, 173)", [11, 92, 173]),
        ("rgb(11 92 173)", [11, 92, 173]),
        ("rgb(11\u00a092\u00a0173)", [11, 92, 173]),  # JavaScript's white space
        ("rgba(0,0,0,0.5)", [128, 128, 128]),  # halves go up, not to even
        ("rgb(0.5, 1.5, 2.5)", [1, 2, 3]),
        ("hsl(210, 100%, 50%)", [0, 128, 255]),
        ("rgb(100%, 0%, 0%)", [255, 0, 0]),
    ],
)
def test_every_accepted_css_form_is_read(value: str, rgb: list[int]) -> None:
    assert colors.parseColor(value) == rgb


@pytest.mark.parametrize(
    "value",
    [
        "",
        "  ",
        "constructor",
        "toString",
        "inherit",
        "transparent",
        "#0000",
        "rgb(1,2)",
        "#12345",
        "rgb(1.2.3, 4, 5)",
        "hsl(1,2,3)",
        "#\u0661\u0661\u0661",  # [0-9] is ASCII
        "rgb(11\u008592\u0085173)",  # not white space to JavaScript
        "rgb(" + " " * 60 + "1,2,3)",  # over 64 characters
    ],
)
def test_what_cannot_be_printed_is_refused(value: str) -> None:
    assert colors.parseColor(value) is _js.UNDEF


def test_readable_colours_print_as_given_and_only_pale_ones_darker() -> None:
    assert colors.printableColor(" rebeccapurple\u00a0", "#1a1a1a") == "rebeccapurple"
    assert colors.printableColor("notacolour", "#1a1a1a") == "#1a1a1a"
    shown = colors.printableColor("#ffe14d", "#1a1a1a")
    assert colors.contrastOnWhite(colors.parseColor(shown)) >= 4.5
    html = pdf.render_kundli_lite_html({}, {"primary_color": "#ffe14d"})
    assert "--brand-primary: #ffe14d" not in html
    assert colors.darkenToContrast([255, 255, 255], 22) == [0, 0, 0]


# -- watermark ---------------------------------------------------------------


def watermark_size(text: str) -> int:
    html = pdf.render_kundli_lite_html({}, {"watermark_text": text})
    found = re.search(r"body::before \{[^}]*font-size: (\d+)pt", html)
    assert found is not None
    return int(found.group(1))


def test_watermark_sizes() -> None:
    assert watermark_size("SAMPLE") == 80
    assert watermark_size("CONFIDENTIAL") == 51
    assert watermark_size("DRAFT FOR REVIEW ONLY") == 61
    assert watermark_size("x" * 500) == 10
    # Code points: nine emoji are nine, not eighteen UTF-16 units.
    assert watermark_size("\U0001f600" * 9) == 68
    for row in fixture("options")["watermarks"]:
        assert watermark_size(row["text"]) == row["size"], ascii(row["text"])


def test_the_watermark_is_behind_the_content_of_brihad() -> None:
    html = brihad({}, {"watermark_text": "SAMPLE"})
    assert 'content: "SAMPLE"' in html
    assert not re.search(r"body::before\s*\{[^}]*display:\s*none", html)
    assert "body::before { z-index: -1; }" in html
    see_through = "tr:nth-child(even) td, .graha-card { background: transparent;"
    assert see_through in html
    assert see_through not in brihad({})


def test_a_see_through_fill_keeps_its_colour_on_white_paper() -> None:
    for value in ("#fcf3e3", "#fffaf0", "#fafafa", "#f0fdf4", "#fef2f2", "#f5f3ff", "#fff7e8"):
        meant = colors.parseColor(value)
        shown = colors.parseColor(colors.seeThrough(meant))
        assert all(abs(a - b) <= 1 for a, b in zip(meant, shown)), value
    assert colors.seeThrough([255, 255, 255]) == "transparent"


@pytest.mark.parametrize("name", RENDERERS)
def test_every_renderer_and_language_prints_the_watermark(name: str) -> None:
    for language in LANGUAGES:
        data = {"Locale": language, "language": language}
        assert 'content: "SAMPLE"' in renderer(name)(data, {"watermark_text": "SAMPLE"})


# -- Brihad palette ----------------------------------------------------------


def test_palette_header_and_footer_match_node() -> None:
    for row in fixture("options")["palettes"]:
        report, caller = or_undefined(row["report"]), or_undefined(row["caller"])
        palette = sections.brihadPalette(report, caller)
        plain = (
            None
            if palette is _js.UNDEF
            else {key: value for key, value in palette.items() if value is not _js.UNDEF}
        )
        assert plain == row["palette"], (report, caller)
        resolved = {"watermarkText": (row["caller"] or {}).get("watermarkText", "")}
        css = sections.brihadPaletteCss(palette) + sections.brihadWatermarkCss(resolved, palette)
        assert css == row["css"], (report, caller)
        assert sections.brihadHeaderTemplate(report, caller) == row["header"], (report, caller)
        assert sections.brihadFooterTemplate(report, caller) == row["footer"], (report, caller)


def test_the_api_default_colours_stay_saffron() -> None:
    respelt = {**API_DEFAULTS, "PrimaryColor": "#1A1A1A", "SecondaryColor": " #666666 "}
    for branding in (_js.UNDEF, API_DEFAULTS, respelt):
        assert sections.brihadPalette(branding) is _js.UNDEF
    passed_on = python_branding({"primaryColor": "#1a1a1a", "secondaryColor": "#666666"})
    assert passed_on is not None
    default_pair = dict(pdf.resolve_branding(API_DEFAULTS))
    assert "--as-teal:#1a1a1a" not in brihad({"Branding": API_DEFAULTS}, passed_on)
    engine = Recorder()
    pdf.kundli_brihad_pdf({"Branding": API_DEFAULTS}, default_pair, engine=engine)
    assert "#9e2b25" in str(engine.options[0].header_template)
    assert "#c25e10" in str(engine.options[0].footer_template)
    assert brihad({"Branding": API_DEFAULTS}) == brihad({})


def test_the_callers_colour_counts_even_when_it_is_the_default_one() -> None:
    engine = printed_brihad({"Branding": API_DEFAULTS}, {"primary_color": "#1a1a1a"})
    assert "color:#1a1a1a" in str(engine.options[0].header_template)
    assert "--as-teal:#1a1a1a" in engine.html[0]


def test_brand_colours_reach_pages_contents_header_and_footer() -> None:
    branding = {"primary_color": "#0b5cad", "secondary_color": "#0b6b36"}
    engine = printed_brihad({"Branding": API_DEFAULTS}, branding)
    final, options = engine.html[-1], engine.options[-1]
    assert "--as-teal:#0b5cad" in final
    assert "--as-amber:#0b6b36" in final
    assert ".toc-row .toc-page { color: #0b5cad !important; }" in final
    for template in (str(options.header_template), str(options.footer_template)):
        assert "color:#0b5cad" in template
        assert "color:#0b6b36" in template
        assert not re.search("#9e2b25|#c25e10", template)
    from_report = {"Branding": {**API_DEFAULTS, "PrimaryColor": "#0b5cad"}}
    assert "color:#0b5cad" in str(printed_brihad(from_report).options[0].header_template)


def test_the_palette_stays_readable_for_any_brand_colour() -> None:
    def contrast(a: Any, b: Any) -> float:
        x, y = colors.contrastOnWhite(a), colors.contrastOnWhite(b)
        return float(max(x, y) / min(x, y))

    fills = [colors.parseColor(v) for v in ("#fafafa", "#f0fdf4", "#fef2f2", "#fefce8")]
    worst_text = worst_banner = 21.0
    steps = range(0, 256, 15)
    for rgb in ([r, g, b] for r in steps[::2] for g in steps[::2] for b in steps[::2]):
        value = colors.toHex(rgb)
        caller = {"primaryColor": value, "secondaryColor": value}
        palette = sections.brihadPalette(_js.UNDEF, caller)
        ink = palette["primary"]
        assert palette["accent"] == palette["muted"] == ink
        worst_banner = min(worst_banner, contrast(ink, [255, 255, 255]))
        for paper in (*fills, colors.tintOnWhite(ink, 5), colors.tintOnWhite(ink, 3)):
            worst_text = min(worst_text, contrast(ink, paper))
    assert worst_banner >= 5.2
    assert worst_text >= 4.5


# -- lookups, labels, the Mangal row, the gem note ---------------------------


def test_names_of_object_properties_are_unknown_words() -> None:
    for word in PROPERTY_NAMES:
        assert planet_glyphs.planetGlyph(word) == ""
        assert locales.southPlanetToEn(word) == ""
        assert locales.localizeLord("te", word) == word
        assert locales.localizeLord(word, "Sun") == "Sun"
        assert locales.localizeWeekday(word, "Sunday") == "Sunday"
        assert sections.renderNorthChart(word, [], "", "en", "#000") == ""
        rows = [{"name": word, "house": 1}, {"name": "Sun", "house": word}]
        assert "<tspan fill" not in sections.renderNorthChart("Aries", rows, "", "en", "#000")


CODED: list[tuple[str, Callable[[str], dict[str, Any]]]] = [
    ("MangalDosha", lambda v: {"Status": v, "HasDosha": True, "HousesOccupied": [7]}),
    ("MatchMaking", lambda v: {"Ashtakoota": {"Verdict": v}}),
    ("SadeSati", lambda v: {"CurrentStatus": {"status": v}}),
    ("Numerology", lambda v: {"driver": v, "driver_factors": {"planet": v, "day": v}}),
    ("KundliDetailed", lambda v: {"Houses": [{"HouseNum": v}]}),
    (
        "KundliBrihad",
        lambda v: {
            "Planets": [{"name_en": v, "house_num": 1}],
            "Houses": [{"HouseNum": v}],
            "Remedies": [{"Category": v}],
            "maitri": {"order": [v], "naisargik": [{"planet": "Sun", "relations": {}}]},
        },
    ),
]


@pytest.mark.parametrize(("name", "data"), CODED, ids=[name for name, _ in CODED])
def test_property_names_neither_raise_nor_print_code(
    name: str, data: Callable[[str], dict[str, Any]]
) -> None:
    for language in LANGUAGES:
        for word in PROPERTY_NAMES:
            html = renderer(name)({"Locale": language, **data(word)})
            assert not re.search(r"native code|\[object|<function", html), (language, word)


@pytest.mark.parametrize("language", LANGUAGES)
def test_mangal_without_a_dosha_has_no_house_row(language: str) -> None:
    empty: list[object] = [None, []]
    for houses in empty:
        html = pdf.render_mangal_dosha_html(
            {"Locale": language, "HasDosha": False, "Status": "none", "HousesOccupied": houses}
        )
        assert "<dd>—</dd>" not in html
        assert html.count("<dt>") == 3
    html = pdf.render_mangal_dosha_html(
        {"Locale": language, "HasDosha": True, "HousesOccupied": [-4]}
    )
    assert html.count("<dt>") == 4


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_gem_note_sends_nobody_to_an_astrologer(language: str) -> None:
    html = brihad({"Locale": language, "gems": {"stones": [{"stone": "x"}]}})
    note = re.search(r'<p class="gems-note">(.*?)</p>', html)
    assert note is not None and note.group(1)
    assert not re.search("astrologer|consult|ज्योतिष", note.group(1), re.IGNORECASE)


def test_english_words_for_the_api_codes() -> None:
    html = brihad(
        {
            "maitri": {
                "order": ["Sun", "Moon"],
                "tatkalik": [
                    {"planet": "Sun", "relations": {"Sun": "TempFriend", "Moon": "TempEnemy"}}
                ],
            },
            "Remedies": [
                {"Title": "A", "Category": "graha_shanti"},
                {"Title": "B", "Category": "charity"},
                {"Title": "C", "Category": "Keep_me"},  # only lower-case ASCII codes change
            ],
        }
    )
    words = ("Temporary friend", "Temporary enemy", "Graha shanti", "Charity", "Keep_me")
    for word in words:
        assert f">{word}<" in html
    assert not re.search("TempFriend|TempEnemy|graha_shanti", html)


def test_short_sections_and_the_friendship_tables() -> None:
    def rajyoga(rows: int) -> str:
        kaal = [{"lord": "Moon"}] * rows
        return brihad({"rajyoga_power": {"percent": 50, "swarnim_kaal": kaal}})

    short = '<section class="section short-section">'
    assert short in rajyoga(2)
    assert short not in rajyoga(3)
    assert ".short-section + .section { page-break-before: auto;" in brihad({})
    html = brihad({"maitri": {"order": ["Sun"], "tatkalik": [{"planet": "Sun"}]}})
    assert '<section class="section maitri-section">' in html
    assert "padding-left: 1.2mm; padding-right: 1.2mm;" in html
    assert "body { color: var(--as-ink); font-size: 11.5pt; line-height: 1.8; }" in html


# -- branding text and blank fields ------------------------------------------

BLANK = {
    "company_name": "\ufeff",
    "logo_url": "\t",
    "primary_color": "\u00a0",
    "secondary_color": "\n",
    "footer_text": " ",
    "watermark_text": " ",
}
REPORT_BRANDING = {
    "CompanyName": "Json Co",
    "LogoURL": "https://j/l.png",
    "PrimaryColor": "#0b5cad",
    "SecondaryColor": "#0b6b36",
    "FooterText": "Json footer",
    "WatermarkText": "JSON",
}


@pytest.mark.parametrize("name", RENDERERS)
def test_blank_caller_branding_is_unset(name: str) -> None:
    render = renderer(name)
    assert render({"Branding": REPORT_BRANDING}, BLANK) == render({"Branding": REPORT_BRANDING})
    assert render({}, BLANK) == render({})


def test_blank_caller_branding_gives_the_same_header_and_footer_as_none() -> None:
    def templates(branding: dict[str, str] | None) -> tuple[str | None, str | None]:
        options = printed_brihad({"Branding": REPORT_BRANDING}, branding).options[0]
        return options.header_template, options.footer_template

    header, footer = templates(BLANK)
    assert "Json Co" in str(header)
    assert "Json footer" in str(footer)
    assert (header, footer) == templates(None)


def test_branding_text_prints_as_written() -> None:
    branding = {"company_name": "Acme — Astro", "footer_text": "© Acme — <private>"}
    html = pdf.render_kundli_lite_html({}, branding)
    assert '<div class="company">Acme — Astro</div>' in html
    assert "<footer>© Acme — &lt;private&gt;</footer>" in html
    options = printed_brihad({}, branding).options[0]
    assert "Acme — Astro" in str(options.header_template)
    assert "© Acme — &lt;private&gt;" in str(options.footer_template)


def test_a_protocol_relative_logo_gets_https() -> None:
    resolved = pdf.resolve_branding(None, {"logo_url": "//cdn.example/l.png"})
    assert resolved["logo_url"] == "https://cdn.example/l.png"


# -- print options -----------------------------------------------------------


def options_from_node(values: dict[str, Any]) -> pdf.PdfOptions:
    margin = values.get("margin")
    return pdf.PdfOptions(
        format=values.get("format", "A4"),
        landscape=values.get("landscape", False),
        prefer_css_page_size=values.get("preferCSSPageSize"),
        print_background=values.get("printBackground", True),
        display_header_footer=values.get("displayHeaderFooter"),
        footer_template=values.get("footerTemplate"),
        margin=None if margin is None else pdf.PdfMargin(**margin),
    )


def test_print_css_matches_node() -> None:
    rows = fixture("options")["print"]
    assert len(rows) > 300
    for row in rows:
        options = options_from_node(row["options"])
        assert _print_css.print_options_css(options) == row["css"], row["options"]


def test_margins_merge_like_node() -> None:
    for row in fixture("options")["merged"]:
        given = None if row["margin"] is None else pdf.PdfMargin(**row["margin"])
        merged = _print_css.merge_margin(sections.BRIHAD_PDF_MARGIN, given)
        assert dataclasses.asdict(merged) == row["merged"], row["margin"]


def test_lengths_outside_the_rule_add_no_css() -> None:
    for value in ("1mm}body{display:none", "-3mm", "10 mm", "1e3", "1.", "\u0661mm", " "):
        assert _print_css.css_length(value) is None, value
    assert _print_css.css_length(12) == "12px"
    assert _print_css.css_length(" 1.5CM ") == "1.5cm"
    assert pdf.PdfMargin(top=96, bottom="\ufeff").inches()[:2] == (1, 0)


def test_without_backgrounds_every_fill_is_clear() -> None:
    clear = (
        "body *, body *::before, body *::after "
        "{ background: transparent !important; box-shadow: none !important; }\n"
    )
    css = _print_css.print_options_css(pdf.PdfOptions(print_background=False))
    assert css.startswith(clear)
    with_page = pdf.PdfOptions(landscape=True, print_background=False)
    after_page = _print_css.print_options_css(with_page).split("}\n", 1)[1]
    assert after_page.startswith(clear)
    assert "background" not in _print_css.print_options_css(pdf.PdfOptions(landscape=True))
    branded = {"company_name": "Acme", "watermark_text": "SAMPLE"}
    options = pdf.PdfOptions(print_background=False)
    for html in printed_brihad({}, branded, options=options).html:
        assert html.count(clear) == 1


def test_default_options_leave_the_html_untouched() -> None:
    html = "<p>x</p>"
    assert _print_css.print_options_css(pdf.PdfOptions()) == ""
    assert _print_css.with_print_css(html, pdf.PdfOptions()) == html
    assert _print_css.with_print_css(html, None) == html
    engine = Recorder()
    pdf.html_to_pdf(html, engine=engine)
    pdf.html_to_pdf(html, options=pdf.PdfOptions(timeout=90), engine=engine)
    assert engine.html == [html, html]


@pytest.fixture
def stub() -> Iterator[DevToolsStub]:
    server = DevToolsStub()
    yield server
    server.close()


LETTER_MARGIN = pdf.PdfOptions(format="Letter", margin=pdf.PdfMargin(top="40mm", left="0"))
LETTER_CSS = (
    "\n<style>@page { margin-top: 40mm !important; margin-left: 0px !important; "
    "size: 8.5in 11in !important; }\n</style>"
)


def test_the_chrome_engine_sends_the_css_and_the_parameters(stub: DevToolsStub) -> None:
    with pdf.ChromePdfEngine.connect(stub.url) as engine:
        engine.html_to_pdf("<p>x</p>")
        assert stub.params("Page.setDocumentContent")["html"] == "<p>x</p>"
        stub.calls.clear()
        engine.html_to_pdf("<p>x</p>", LETTER_MARGIN)
        assert stub.params("Page.setDocumentContent")["html"] == "<p>x</p>" + LETTER_CSS
        params = stub.params("Page.printToPDF")
        assert (params["paperWidth"], params["paperHeight"]) == (8.5, 11)
        assert params["marginTop"] == pytest.approx(40 / 25.4)
        assert params["displayHeaderFooter"] is False
        stub.calls.clear()
        # Through a one-call function and the engine: the CSS is there once.
        pdf.html_to_pdf("<p>x</p>", options=LETTER_MARGIN, engine=engine)
        assert stub.params("Page.setDocumentContent")["html"] == "<p>x</p>" + LETTER_CSS


def test_the_gotenberg_engine_sends_the_css_and_the_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    sent: list[dict[str, Any]] = []

    def post(url: str, **kwargs: Any) -> httpx.Response:
        sent.append(kwargs)
        return httpx.Response(200, content=b"%PDF-stub")

    async def post_async(self: Any, url: str, **kwargs: Any) -> httpx.Response:
        return post(url, **kwargs)

    monkeypatch.setattr(httpx.Client, "post", lambda self, url, **kwargs: post(url, **kwargs))
    monkeypatch.setattr(httpx.AsyncClient, "post", post_async)
    engine = pdf.GotenbergPdfEngine("http://localhost:3000")
    engine.html_to_pdf("<p>x</p>")
    engine.html_to_pdf("<p>x</p>", LETTER_MARGIN)
    asyncio.run(engine.html_to_pdf_async("<p>x</p>", LETTER_MARGIN))
    pdf.html_to_pdf("<p>x</p>", options=LETTER_MARGIN, engine=engine)
    assert dict(sent[0]["files"])["files"][1] == b"<p>x</p>"
    for call in sent[1:]:
        assert dict(call["files"])["files"][1] == ("<p>x</p>" + LETTER_CSS).encode()
        assert call["data"]["paperWidth"] == "8.5"


@pytest.mark.parametrize("name", RENDERERS)
def test_every_one_call_function_gives_any_engine_the_css(name: str) -> None:
    engine = Recorder()
    options = pdf.PdfOptions(landscape=True, print_background=False)
    getattr(pdf, f"{snake(name)}_pdf")({}, options=options, engine=engine)
    for html in engine.html:
        assert html.count("size: 297mm 210mm !important;") == 1
        assert html.count("print-color-adjust: economy !important; }") == 1


# -- the Brihad wrapper ------------------------------------------------------


def test_brihad_defaults() -> None:
    engine = printed_brihad({})
    options = engine.options[0]
    assert options.display_header_footer is True
    assert options.margin == pdf.PdfMargin(top="26mm", bottom="16mm", left="0mm", right="0mm")
    for html in engine.html:
        assert html.endswith(
            "\n<style>@page { margin-top: 26mm !important; margin-right: 0mm !important; "
            "margin-bottom: 16mm !important; margin-left: 0mm !important; "
            "@bottom-center { content: none !important; } }\n</style>"
        )


def test_the_callers_header_footer_and_margins_reach_brihad() -> None:
    options = pdf.PdfOptions(
        margin=pdf.PdfMargin(top="40mm", bottom=" ", left="0"),
        format="A5",
        header_template="<p>my header</p>",
        footer_template="<p>my footer</p>",
    )
    engine = printed_brihad({}, options=options)
    got = engine.options[0]
    assert got.margin == pdf.PdfMargin(top="40mm", bottom="16mm", left="0", right="0mm")
    assert (got.header_template, got.footer_template) == ("<p>my header</p>", "<p>my footer</p>")
    assert "size: 148mm 210mm !important;" in engine.html[0]
    blank = printed_brihad({}, options=pdf.PdfOptions(header_template="", footer_template=""))
    assert "LifeAstro" in str(blank.options[0].header_template)
    assert "pageNumber" in str(blank.options[0].header_template)


def test_brihad_header_and_footer_are_off_only_when_the_caller_says_false() -> None:
    assert pdf.PdfOptions().display_header_footer is None  # "not said"
    assert printed_brihad({}, options=pdf.PdfOptions()).options[0].display_header_footer is True
    off = printed_brihad({}, options=pdf.PdfOptions(display_header_footer=False))
    assert off.options[0].display_header_footer is False
    assert "@bottom-center { content: none" not in off.html[0]
    assert "margin-top: 26mm !important;" in off.html[0]


def test_a_long_brihad_can_be_given_more_time() -> None:
    options = pdf.PdfOptions(timeout=120, print_timeout=900)
    for used in printed_brihad({}, options=options).options:
        assert (used.timeout, used.print_timeout) == (120, 900)


def test_markers_open_their_section_with_nothing_between() -> None:
    tagged = sections.tagBrihadSectionsForToc(brihad(example("KundliBrihad", "en")))["html"]
    marker = r'<span style="color:#fff;font-size:1px;">⟦T\d+⟧</span>'
    pairs = re.findall(
        rf'<section class="section[^"]*" data-toc-title="[^"]*">{marker}{marker}<div class="part',
        tagged,
    )
    singles = re.findall(rf'<section class="section[^"]*"[^>]*>(?:{marker})', tagged)
    assert pairs
    assert len(singles) == tagged.count("data-toc-title=")
    hidden = _reports._hide_markers(tagged)
    assert re.search(r'data-toc-title="[^"]*"><span style="[^"]*">&nbsp;</span><span ', hidden)
    css = brihad({})
    assert ".section > span:first-child, .section > span:first-child + span {" in css


def test_sections_may_share_a_page() -> None:
    engine = Recorder(sections_per_page=3)
    report = {
        "Planets": [{"name": "Sun", "house_num": 1}],
        "avakahada": {"paya": "Gold"},
        "panchang": {"tithi": "1"},
    }
    out = pdf.kundli_brihad_pdf(report, engine=engine)
    numbers = re.findall(r'class="toc-page"[^>]*>(\d+)</span>', engine.html[-1])
    assert numbers[:4] == ["3", "3", "3", "4"]
    targets = re.findall(rb"/Dest \[(\d+) 0 R /Fit\]", out)
    assert len(targets) == len(numbers)  # a bookmark for each, sharing pages
    assert len(set(targets)) < len(targets)


# -- a field that should be a list -------------------------------------------

NOT_A_LIST = ("1, 5", {"a": 1}, 7, 2.5, True, False, "", None)
#: Where the templates read a list that a malformed report may not hold.
LIST_SITES: tuple[tuple[str, Callable[[Any], dict[str, Any]]], ...] = (
    ("KundliBrihad", lambda v: {"narrative_chapters": v}),
    (
        "KundliBrihad",
        lambda v: {"DivisionalCharts": [{"varga": "D9", "lagna_sign": "Leo", "planets": v}]},
    ),
    ("KundliBrihad", lambda v: {"gems": {"stones": v}}),
    ("KundliBrihad", lambda v: {"chalit": {"houses": [{"house": 1}], "planets": v}}),
    ("KundliBrihad", lambda v: {"kp": {"cusps": [{"house": 1}], "planet_significators": v}}),
    ("KundliBrihad", lambda v: {"jaimini": {"charakarakas": v}}),
    ("KundliBrihad", lambda v: {"jaimini": {"arudha_padas": v}}),
    ("KundliBrihad", lambda v: {"lal_kitab": {"planets": v}}),
    ("KundliBrihad", lambda v: {"lal_kitab": {"rins": v}}),
    ("KundliBrihad", lambda v: {"ashtakavarga": {"sav": [28], "prastar": v}}),
    ("KundliBrihad", lambda v: {"varshaphal": [{"year": 2027, "sahams": v}]}),
    ("KundliBrihad", lambda v: {"varshaphal": [{"year": 2027, "panchavargeeya": v}]}),
    ("KundliBrihad", lambda v: {"mudda_timeline": {"periods": [{"areas": v}]}}),
    ("KundliBrihad", lambda v: {"rajyoga_power": {"percent": 5, "swarnim_kaal": v}}),
    *(
        (
            "MatchMaking",
            lambda v, locale=locale, who=who: {
                "Locale": locale,
                who: {"Computed": True, "HasDosha": True, "HousesOccupied": v},
            },
        )
        for locale in LANGUAGES
        for who in ("MangalDoshaBoy", "MangalDoshaGirl")
    ),
)
#: Where a list prints joined, and a lone text or number as it is.
TEXT_SITES: tuple[tuple[str, Callable[[Any], dict[str, Any]]], ...] = (
    (
        "KundliBrihad",
        lambda v: {
            "kp": {"cusps": [{"house": 1}], "planet_significators": [{"key": "Sun", "values": v}]}
        },
    ),
    ("KundliBrihad", lambda v: {"rajyoga_power": {"percent": 5, "planets": v}}),
    ("SadeSati", lambda v: {"Past": [{"SignsTraversed": v}]}),
    ("SadeSati", lambda v: {"Future": [{"SignsTraversed": v}]}),
    ("SadeSati", lambda v: {"Current": {"SignsTraversed": v}}),
)


@pytest.mark.parametrize("site", range(len(LIST_SITES)))
def test_what_is_not_a_list_prints_like_an_empty_one(site: int) -> None:
    name, report = LIST_SITES[site]
    empty = renderer(name)(report([]))
    for value in NOT_A_LIST:
        assert renderer(name)(report(value)) == empty, value


@pytest.mark.parametrize("site", range(len(TEXT_SITES)))
def test_a_lone_value_prints_as_it_is(site: int) -> None:
    name, report = TEXT_SITES[site]
    render = renderer(name)
    assert render(report("1, 5")) == render(report(["1, 5"]))
    assert render(report(7)) == render(report(["7"]))
    assert render(report(2.5)) == render(report(["2.5"]))
    assert "&lt;b&gt;" in render(report("<b>"))
    for value in ({"a": 1}, True, False, "", None):
        assert render(report(value)) == render(report([])), value


def list_fields(value: Any, path: tuple[Any, ...], shape: str, found: dict[str, Any]) -> None:
    """One path for every different list in a report."""
    if isinstance(value, list):
        found.setdefault(shape, path)
        for index, item in enumerate(value):
            list_fields(item, (*path, index), f"{shape}[]", found)
    elif isinstance(value, dict):
        for key, item in value.items():
            list_fields(item, (*path, key), f"{shape}.{key}", found)


@pytest.mark.parametrize("name", [name for name in RENDERERS if name != "Horoscope"])
def test_no_list_field_can_stop_a_render(name: str) -> None:
    report = example(name, "en")
    paths: dict[str, tuple[Any, ...]] = {}
    list_fields(report, (), "", paths)
    for shape, (*parents, last) in paths.items():
        for value in ("1, 5", {"a": 1}, 7):
            broken = copy.deepcopy(report)
            holder: Any = broken
            for key in parents:
                holder = holder[key]
            holder[last] = value
            assert renderer(name)(broken).startswith("<!"), (shape, value)


# -- a null inside a list ----------------------------------------------------


@pytest.mark.parametrize(
    ("name", "data"),
    [
        # The cases of "a null inside a list" in the Node SDK's tests.
        ("KundliBrihad", {"Planets": [None]}),
        ("KundliBrihad", {"Planets": ["x", None]}),
        ("KundliBrihad", {"Planets": [7, None]}),
        ("KundliBrihad", {"narrative_chapters": [{"key": "outlook"}, None]}),
        ("KundliDetailed", {"Planets": [{}, None]}),
        ("DashaAnalysis", {"AllMahadashas": [None]}),
        ("Horoscope", {"slow_movers": [None]}),
    ],
)
def test_a_null_inside_a_list_is_skipped(name: str, data: dict[str, Any]) -> None:
    assert renderer(name)(data).startswith("<!")


def test_a_null_item_prints_like_a_list_without_it() -> None:
    sun = {"name": "Sun", "house_num": 1}
    assert brihad({"Planets": [None, sun, None]}) == brihad({"Planets": [sun]})
    assert brihad({"Planets": [None]}) == brihad({"Planets": []})
    # Among plain values the places of the others hold.
    with_null = brihad({"ashtakavarga": {"sav": [28, None, 30]}})
    assert with_null == brihad({"ashtakavarga": {"sav": [28, "", 30]}})


@pytest.mark.parametrize(
    ("given", "printed"),
    [
        ([1, None, "x", False], [1, "", "x", False]),
        ([None, "", 0], ["", "", 0]),
        ([None], []),
        ([None, None], []),
        ([{"a": 1}, None], [{"a": 1}]),
        ([7, None, [1]], [7, [1]]),
        ([[None]], [[]]),
        ({"a": {"b": [None, {"c": [None, 2]}]}}, {"a": {"b": [{"c": ["", 2]}]}}),
        ((1, None), [1, ""]),
    ],
)
def test_nulls_leave_lists_like_in_node(given: Any, printed: Any) -> None:
    before = copy.deepcopy(given)
    assert shared.withoutNullItems(given) == printed
    assert given == before


def test_a_report_without_such_a_null_comes_back_as_it_is() -> None:
    report = {"a": None, "b": [1, 2.5, True, {"c": None, "d": ["x"]}], "e": float("nan")}
    assert shared.withoutNullItems(report)["b"] is report["b"]
    clean = {"a": None, "b": [1, 2.5, True, {"c": None, "d": ["x"]}]}
    assert shared.withoutNullItems(clean) is clean
    changed = shared.withoutNullItems({"same": clean, "list": [None]})
    assert changed["same"] is clean
    deep: Any = [None]
    for _ in range(40):
        deep = {"x": deep}
    assert shared.withoutNullItems(deep) is deep  # below the depth cap
    loop: dict[str, Any] = {}
    loop["self"] = loop
    assert shared.withoutNullItems(loop) is loop


@pytest.mark.parametrize("name", RENDERERS)
def test_a_null_does_not_edit_the_callers_report(name: str) -> None:
    data = {"Planets": [None, {"name": "Sun"}], "Nested": {"List": [1, None]}}
    before = copy.deepcopy(data)
    renderer(name)(data)
    assert data == before


def test_a_brihad_pdf_with_nulls_in_its_lists() -> None:
    chapters = [None, {"key": "outlook", "title": "Outlook"}]
    planets = [None, {"name": "Sun", "house_num": 1}]
    report = {"Planets": planets, "narrative_chapters": chapters}
    clean = {"Planets": planets[1:], "narrative_chapters": chapters[1:]}
    assert printed_brihad(report).html == printed_brihad(clean).html
    assert chapters[0] is None


@pytest.mark.parametrize("name", RENDERERS)
def test_no_null_inside_a_list_can_stop_a_render(name: str) -> None:
    key = "language" if name == "Horoscope" else "Locale"
    reports = [
        case["data"]
        for case in fixture("cases")
        if case["fn"] == f"render{name}Html" and case["data"].get(key) in (None, "", "en")
    ]
    assert reports
    for report in reports:
        paths: dict[str, tuple[Any, ...]] = {}
        list_fields(report, (), "", paths)
        for shape, path in paths.items():
            for kind in (None, [None], ["x", None], [7, None], [[None]]):
                broken = copy.deepcopy(report)
                holder: Any = broken
                for step in path:
                    holder = holder[step]
                if kind is None:
                    holder.append(None)
                else:
                    holder[:] = copy.deepcopy(kind)
                assert renderer(name)(broken).startswith("<!"), (shape, kind)


# -- in print ----------------------------------------------------------------

needs_browser = pytest.mark.skipif(
    pdf.find_browser() is None,
    reason="no Chrome, Chromium or Edge installed (set LIFEASTRO_CHROME to point at one)",
)


@pytest.fixture(scope="module")
def chrome() -> Iterator[pdf.ChromePdfEngine]:
    with pdf.ChromePdfEngine() as engine:
        yield engine


def media_box(data: bytes) -> tuple[int, int]:
    found = re.search(rb"/MediaBox \[0 0 ([0-9.]+) ([0-9.]+)\]", data)
    assert found is not None
    return round(float(found.group(1))), round(float(found.group(2)))


@needs_browser
@pytest.mark.parametrize(
    ("options", "size"),
    [
        (pdf.PdfOptions(), (595, 842)),
        (pdf.PdfOptions(format="Letter"), (612, 792)),
        (pdf.PdfOptions(landscape=True), (842, 595)),
        (pdf.PdfOptions(format="A5", landscape=True), (595, 420)),
        (pdf.PdfOptions(format="A5", prefer_css_page_size=True), (595, 842)),
    ],
)
def test_paper_options_reach_a_report(
    options: pdf.PdfOptions, size: tuple[int, int], chrome: pdf.ChromePdfEngine
) -> None:
    data = pdf.kundli_lite_pdf(example("KundliLite", "en"), options=options, engine=chrome)
    assert media_box(data) == pytest.approx(size, abs=1)


def tool(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        pytest.skip(f"{name} is not installed")
    return found


@needs_browser
def test_a_margin_and_a_callers_footer_reach_a_report(
    chrome: pdf.ChromePdfEngine, tmp_path: Path
) -> None:
    pdftotext = tool("pdftotext")
    path = tmp_path / "report.pdf"
    options = pdf.PdfOptions(
        margin=pdf.PdfMargin(left="50mm"),
        display_header_footer=True,
        footer_template='<div style="font-size:9px;margin:auto">CALLER-FOOTER</div>',
    )
    path.write_bytes(
        pdf.kundli_lite_pdf(example("KundliLite", "en"), options=options, engine=chrome)
    )
    run = subprocess.run([pdftotext, "-bbox", str(path), "-"], capture_output=True, check=True)
    words = run.stdout.decode("utf-8")
    assert "CALLER-FOOTER" in words
    assert ">LifeAstroAPI</word>" not in words  # the report's own footer line gave way
    plain = tmp_path / "plain.pdf"
    plain.write_bytes(pdf.kundli_lite_pdf(example("KundliLite", "en"), engine=chrome))
    default = subprocess.run([pdftotext, "-bbox", str(plain), "-"], capture_output=True, check=True)
    assert b">LifeAstroAPI</word>" in default.stdout
    second = words.split("<page ")[2]
    body = [
        float(x)
        for x, y in re.findall(r'<word xMin="([0-9.]+)" yMin="([0-9.]+)"', second)
        if float(y) < 750
    ]
    assert min(body) >= 141  # 50 mm


@needs_browser
@pytest.mark.parametrize("language", ["en", "ml"])
def test_brihad_contents_add_only_their_own_pages(
    language: str, chrome: pdf.ChromePdfEngine
) -> None:
    documents: list[tuple[str, pdf.PdfOptions]] = []

    class Keep:
        def html_to_pdf(
            self,
            html: str,
            options: pdf.PdfOptions | None = None,
            *,
            cancel: threading.Event | None = None,
        ) -> bytes:
            assert options is not None
            documents.append((html, options))
            return chrome.html_to_pdf(html, options, cancel=cancel)

    report = example("KundliBrihad", language)
    full = page_count(pdf.kundli_brihad_pdf(report, engine=Keep()))
    final, options = documents[-1]
    plain = page_count(chrome.html_to_pdf(pdf.render_kundli_brihad_html(report), options))
    head = final.partition('<section class="section first"')[0] + "</body></html>"
    cover_and_contents = page_count(chrome.html_to_pdf(head, options))
    assert full == plain + cover_and_contents - 1


@needs_browser
def test_without_backgrounds_a_see_through_fill_hides_nothing(
    chrome: pdf.ChromePdfEngine, tmp_path: Path
) -> None:
    pdftoppm = tool("pdftoppm")
    html = (
        "<!doctype html><style>body { -webkit-print-color-adjust: exact; }</style><body>"
        '<svg style="position: fixed; top: 0; left: 0; z-index: -1" width="600" height="600">'
        '<rect width="600" height="600" fill="#000"/></svg>'
        '<div style="height: 600px; background: rgba(250, 240, 220, 0.25); '
        'box-shadow: 0 0 2px #ccc">x</div>'
    )
    path = tmp_path / "page.pdf"
    path.write_bytes(chrome.html_to_pdf(html, pdf.PdfOptions(print_background=False)))
    subprocess.run(
        [pdftoppm, "-gray", "-r", "20", "-singlefile", str(path), str(tmp_path / "page")],
        check=True,
    )
    header = re.match(rb"P5\s+(\d+)\s+(\d+)\s+255\s", (tmp_path / "page.pgm").read_bytes())
    assert header is not None
    pixels = (tmp_path / "page.pgm").read_bytes()[header.end() :]
    assert sum(value < 40 for value in pixels) > len(pixels) // 5
