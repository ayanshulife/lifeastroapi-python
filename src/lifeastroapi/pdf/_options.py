"""Options, the engine interface and the error of :mod:`lifeastroapi.pdf`."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Literal, Protocol, Union

from ..errors import LifeAstroError
from . import _js

#: Paper sizes, as Puppeteer defines them. The report templates use A4.
PaperFormat = Literal["A3", "A4", "A5", "Letter", "Legal", "Tabloid"]

#: A CSS length such as ``"10mm"``, or a number of CSS pixels.
Length = Union[str, float]

_PAPER_INCHES: dict[str, tuple[float, float]] = {
    "A3": (11.6929, 16.5354),
    "A4": (8.2677, 11.6929),
    "A5": (5.8268, 8.2677),
    "Letter": (8.5, 11.0),
    "Legal": (8.5, 14.0),
    "Tabloid": (11.0, 17.0),
}
_CSS_LENGTH = re.compile(r"\s*(-?[0-9]*\.?[0-9]+)\s*(px|in|cm|mm)?\s*", re.ASCII | re.IGNORECASE)
_PER_INCH = {"px": 96.0, "in": 1.0, "cm": 2.54, "mm": 25.4}


class PdfError(LifeAstroError):
    """HTML could not be printed to PDF.

    ``code`` says why: ``browser_not_found``, ``browser_failed``, ``timeout``,
    ``cancelled``, ``closed``, ``gotenberg_failed`` or ``invalid_pdf``.
    """

    def __init__(self, message: str, *, code: str = "pdf_failed") -> None:
        super().__init__(message, code=code, status=0)


def length_text(value: Length | None) -> str:
    """A length as JavaScript reads it: trimmed, ``""`` when not set, a number without ``.0``."""
    if value is None:
        return ""
    if isinstance(value, str):
        return _js.trim(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"not a CSS length: {value!r}")
    return _js.number_to_string(value)


def css_length_to_inches(value: Length | None) -> float:
    """``"26mm"``, ``"1cm"``, ``"0.5in"``, ``"20px"``, ``"20"`` or ``20`` (pixels), in inches."""
    text = length_text(value)
    if not text:
        return 0.0
    found = _CSS_LENGTH.fullmatch(text)
    if found is None:
        raise ValueError(f"not a CSS length: {value!r} (use for example '10mm' or '0.5in')")
    return float(found.group(1)) / _PER_INCH[(found.group(2) or "px").lower()]


@dataclass(frozen=True)
class PdfMargin:
    """Page margins as CSS lengths (``"10mm"``, ``"1cm"``, ``"0.5in"``, ``"20px"``, ``20``).

    A side you set wins over the page's own CSS. A side that is not set keeps the page's
    own margin, which is 0 for HTML that has none. ``"0"`` is zero.
    """

    top: Length | None = None
    bottom: Length | None = None
    left: Length | None = None
    right: Length | None = None

    def __post_init__(self) -> None:
        self.inches()  # a bad length fails here, not after the browser has started

    def inches(self) -> tuple[float, float, float, float]:
        """``(top, bottom, left, right)`` in inches."""
        return (
            css_length_to_inches(self.top),
            css_length_to_inches(self.bottom),
            css_length_to_inches(self.left),
            css_length_to_inches(self.right),
        )


@dataclass(frozen=True)
class PdfOptions:
    """How to print. The defaults are right for every report.

    What you set here wins over the report's own CSS.
    """

    format: PaperFormat = "A4"
    """Paper size. One other than A4 wins over the page's CSS size; A4, the default, does not."""
    landscape: bool = False
    """Landscape paper, also for the reports."""
    print_background: bool = True
    """Print background colours and images (the templates are branded). With ``False``,
    text that is white on colour prints dark."""
    prefer_css_page_size: bool | None = None
    """``True``: the HTML's own ``@page`` size, whatever ``format`` and ``landscape`` say.
    ``False``: scale the page to the paper. Default: the HTML's own size, unless ``format``
    or ``landscape`` is given, or a running header and footer are on."""
    margin: PdfMargin | None = None
    """Page margins. Each side you set wins over the page's own CSS."""
    display_header_footer: bool | None = None
    """Print ``header_template`` and ``footer_template`` in the page margin, instead of the
    report's own footer line. Default: off, and on for the Brihad kundli, which ``False``
    turns off."""
    header_template: str | None = None
    """Running header HTML, inline styles only. The browser fills
    ``<span class="pageNumber">``, ``totalPages``, ``title``, ``date`` and ``url``."""
    footer_template: str | None = None
    """Running footer HTML, inline styles only. With ``display_header_footer`` it replaces
    the report's own footer line."""
    scale: float | None = None
    """Render scale, 0.1 to 2."""
    timeout: float = 30.0
    """Seconds allowed for the page, its images and its fonts to load."""
    print_timeout: float = 180.0
    """Seconds allowed for each print. The Brihad kundli runs to a few hundred pages and
    prints twice: raise this on a slow machine."""

    def __post_init__(self) -> None:
        if self.format not in _PAPER_INCHES:
            names = ", ".join(_PAPER_INCHES)
            raise ValueError(f"unknown paper format {self.format!r} (use one of {names})")
        if self.scale is not None and not 0.1 <= self.scale <= 2:
            raise ValueError("scale must be between 0.1 and 2")
        if self.timeout <= 0 or self.print_timeout <= 0:
            raise ValueError("timeout and print_timeout must be positive")

    def paper_inches(self) -> tuple[float, float]:
        """``(width, height)`` in inches, after orientation."""
        width, height = _PAPER_INCHES[self.format]
        return (height, width) if self.landscape else (width, height)

    def uses_css_page_size(self) -> bool:
        # The header and footer live in the margin, which a CSS page size would collapse.
        if self.display_header_footer:
            return False
        return True if self.prefer_css_page_size is None else self.prefer_css_page_size


class PdfEngine(Protocol):
    """Prints a complete HTML document to PDF bytes.

    The SDK ships ``ChromePdfEngine`` and ``GotenbergPdfEngine``. Any object with this
    method can be passed as ``engine=``.
    """

    def html_to_pdf(
        self,
        html: str,
        options: PdfOptions | None = None,
        *,
        cancel: threading.Event | None = None,
    ) -> bytes:
        """Return the PDF. Stop with :class:`PdfError` once ``cancel`` is set."""
        ...


def check_cancelled(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise PdfError("The PDF job was cancelled", code="cancelled")


def printable(html: str) -> str:
    """Lone surrogates become U+FFFD, as when JavaScript writes the string as UTF-8."""
    try:
        html.encode("utf-8")
    except UnicodeEncodeError:
        return html.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")
    return html
