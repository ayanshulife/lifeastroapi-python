"""Branding of the reports, and the text helpers of the templates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypedDict

from ._js import UNDEF


class Branding(TypedDict, total=False):
    """Your branding for a report. Every key is optional.

    A key you set wins over the ``Branding`` inside the report JSON; the rest falls back
    to it, then to the defaults. A plain ``dict`` with these keys works too.
    """

    company_name: str
    """Shown on the cover, and in the running header of the Brihad kundli."""
    logo_url: str
    """Logo URL or ``data:image/...`` URI, at the top of the cover. ``//host/logo.png`` is
    read as https; other schemes are dropped."""
    primary_color: str
    """Accent colour for headings and table headers, for example ``#6b21a8``. The Brihad
    kundli also takes it for banners, contents, charts and running header. A colour too
    pale to read is darkened."""
    secondary_color: str
    """Colour of meta text and the footer, and of the Brihad kundli's gold details."""
    footer_text: str
    """Footer line on every page, printed as written. Default: ``Generated using LifeAstroAPI``."""
    watermark_text: str
    """Diagonal watermark on every page, for example ``SAMPLE``. A long one prints smaller."""


#: key here -> (key of the templates, key inside the report JSON)
_KEYS = {
    "company_name": ("companyName", "CompanyName"),
    "logo_url": ("logoUrl", "LogoURL"),
    "primary_color": ("primaryColor", "PrimaryColor"),
    "secondary_color": ("secondaryColor", "SecondaryColor"),
    "footer_text": ("footerText", "FooterText"),
    "watermark_text": ("watermarkText", "WatermarkText"),
}


def _checked(branding: Mapping[str, object]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in branding.items():
        if key not in _KEYS:
            names = ", ".join(_KEYS)
            raise ValueError(f"unknown branding key {key!r} (use {names})")
        if value is None:
            continue
        if not isinstance(value, str):
            raise TypeError(f"branding {key!r} must be a string, got {type(value).__name__}")
        out[key] = value
    return out


def template_branding(branding: Mapping[str, object] | None) -> Any:
    """The branding as the generated templates take it."""
    if branding is None:
        return UNDEF
    return {_KEYS[key][0]: value for key, value in _checked(branding).items()}


def resolve_branding(
    embedded: Mapping[str, object] | None = None, branding: Mapping[str, object] | None = None
) -> Branding:
    """The branding a report prints with.

    :param embedded: The ``Branding`` of the report JSON.
    :param branding: Your overrides.
    """
    from ._templates import shared

    resolved = shared.resolveBranding(
        UNDEF if embedded is None else embedded, template_branding(branding)
    )
    return Branding(
        company_name=resolved["companyName"],
        logo_url=resolved["logoUrl"],
        primary_color=resolved["primaryColor"],
        secondary_color=resolved["secondaryColor"],
        footer_text=resolved["footerText"],
        watermark_text=resolved["watermarkText"],
    )


def esc(value: object) -> str:
    """HTML-escape a value the way the templates do (dashes and arrows in prose become commas)."""
    from ._templates import shared

    return str(shared.esc(value))


def esc_body(value: object, locale: str = "en") -> str:
    """:func:`clean_narrative`, then :func:`esc`: for a narrative paragraph."""
    from ._templates import shared

    return str(shared.escBody(value, locale))


def humanize(text: str) -> str:
    """Replace dashes and arrows used in prose by commas."""
    from ._templates import shared

    return str(shared.humanize(text))


def clean_narrative(text: str, locale: str = "en") -> str:
    """Make an authored narrative read in the second person, as the reports do."""
    from ._templates import shared

    return str(shared.cleanNarrative(text, locale))
