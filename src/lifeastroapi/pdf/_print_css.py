"""The options that a page's own print CSS would otherwise win over, as CSS that wins over it.

A hand port of ``printOptionsCss`` and ``mergeMargin`` in the Node SDK's ``src/pdf/render.ts``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from ._options import Length, PdfMargin, PdfOptions, length_text

#: ``format`` as a CSS ``size``: width, height, unit.
_PAPER = {
    "a3": ("297", "420", "mm"),
    "a4": ("210", "297", "mm"),
    "a5": ("148", "210", "mm"),
    "letter": ("8.5", "11", "in"),
    "legal": ("8.5", "14", "in"),
    "tabloid": ("11", "17", "in"),
}
_CSS_LENGTH = re.compile(r"([0-9]+(?:\.[0-9]+)?|\.[0-9]+)(px|in|cm|mm)?", re.ASCII | re.IGNORECASE)
_SIDES = ("top", "right", "bottom", "left")

#: The reports ask for exact colours, which prints backgrounds whatever the browser is told.
#: Without them, text that is white on a coloured background needs ink.
_NO_BACKGROUNDS = (
    # Economy printing paints a see-through fill solid white, which cut the watermark into strips.
    "body *, body *::before, body *::after "
    "{ background: transparent !important; box-shadow: none !important; }\n"
    "html { -webkit-print-color-adjust: economy !important; "
    "print-color-adjust: economy !important; }\n"
    "th, .part-banner .part-h2, .toc-banner, .summary-card, .num-chip, .number-block .number, "
    ".moon-sign-badge, .year-badge, .remedy-block .category, .dosha-block .severity, "
    ".yoga-block .name::before { color: #1a1a1a !important; }\n"
)


def css_length(value: Length | None) -> str | None:
    """A margin as Puppeteer reads it (no unit is px). ``None`` when unset or not a length."""
    found = _CSS_LENGTH.fullmatch(length_text(value))
    return found.group(1) + (found.group(2) or "px").lower() if found else None


def print_options_css(options: PdfOptions) -> str:
    """The CSS for these options. ``""`` when none of them needs any."""
    page: list[str] = []
    for side in _SIDES:
        value = css_length(getattr(options.margin, side)) if options.margin is not None else None
        if value:
            page.append(f"margin-{side}: {value} !important;")
    # An explicit prefer_css_page_size keeps its meaning: True is the CSS size, False scales
    # to the paper. Portrait A4 is the default, so it never overrides a CSS size.
    name = options.format.lower()
    if options.prefer_css_page_size is None and (name != "a4" or options.landscape):
        paper = _PAPER.get(name)
        if paper is not None:
            width, height, unit = paper
            if options.landscape:
                width, height = height, width
            page.append(f"size: {width}{unit} {height}{unit} !important;")
    if options.display_header_footer and options.footer_template is not None:
        page.append("@bottom-center { content: none !important; }")
    css = f"@page {{ {' '.join(page)} }}\n" if page else ""
    if options.print_background is False:
        css += _NO_BACKGROUNDS
    return css


def with_print_css(html: str, options: PdfOptions | None) -> str:
    """``html`` followed by the CSS of ``options``. Untouched with the default options.

    The one-call functions and the built-in engines all use it, so it never adds twice.
    """
    css = print_options_css(options) if options is not None else ""
    if not css:
        return html
    style = f"\n<style>{css}</style>"
    return html if html.endswith(style) else html + style


def merge_margin(defaults: Mapping[str, str], given: PdfMargin | None) -> PdfMargin:
    """The defaults, side by side replaced by what the caller set. ``"0"`` is zero."""
    sides: dict[str, Length] = dict(defaults)
    if given is not None:
        for side in _SIDES:
            value: Length | None = getattr(given, side)
            if value is not None and length_text(value):
                sides[side] = value
    return PdfMargin(**sides)
