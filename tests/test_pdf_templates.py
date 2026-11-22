"""The templates give byte-for-byte the HTML of the Node SDK.

Committed cases: ``scripts/pdf_goldens.mjs``. The deep test renders every full report of
the shared reference (``LIFEASTRO_PDF_WORK``, default ``../LifeAstroAPI/pdf_work``) and
runs only where that exists.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from lifeastroapi import pdf
from lifeastroapi.pdf._templates import kundli_brihad_sections as sections
from lifeastroapi.pdf._templates import locales, north_indian_chart, shared

from conftest import Recorder, make_client, reply
from pdf_support import (
    BRANDING,
    FIXTURES,
    PDF_WORK,
    RENDERERS,
    fixture,
    python_branding,
    renderer,
)

CASE_IDS = (
    [case["id"] for case in fixture("cases")]
    if (FIXTURES / "cases.json.gz").is_file()
    else [pytest.param("", marks=pytest.mark.skip(reason="no fixtures in the sdist"))]
)
MANIFEST: list[dict[str, Any]] = (
    json.loads((PDF_WORK / "manifest.json").read_text(encoding="utf-8"))["cases"]
    if (PDF_WORK / "manifest.json").is_file()
    else []
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _difference(case: str, expected: str, actual: str) -> str:
    at = next(
        (i for i, (a, b) in enumerate(zip(expected, actual)) if a != b),
        min(len(expected), len(actual)),
    )
    start = max(0, at - 120)
    return (
        f"{case} differs from Node at character {at}\n"
        f"--- Node ---\n{expected[start : at + 120]!r}\n"
        f"--- Python ---\n{actual[start : at + 120]!r}"
    )


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_renders_like_node(case_id: str) -> None:
    case = next(c for c in fixture("cases") if c["id"] == case_id)
    name = case["fn"][len("render") : -len("Html")]
    html = renderer(name)(case["data"], python_branding(case["branding"]))
    if "html" in case and html != case["html"]:
        pytest.fail(_difference(case_id, case["html"], html))
    assert _sha256(html) == case["sha256"], case_id


def test_every_node_renderer_is_ported() -> None:
    used = {case["fn"] for case in fixture("cases")}
    assert used == {f"render{name}Html" for name in RENDERERS}


@pytest.mark.skipif(not MANIFEST, reason=f"no shared PDF reference at {PDF_WORK}")
@pytest.mark.parametrize("case", MANIFEST, ids=[case["id"] for case in MANIFEST])
def test_deep_parity_with_the_shared_reference(case: dict[str, Any]) -> None:
    data = json.loads((PDF_WORK / "inputs" / case["input"]).read_text(encoding="utf-8"))
    html = renderer(case["renderer"])(data, python_branding(case["branding"]))
    if _sha256(html) != case["sha256"]:
        expected = (PDF_WORK / "expected" / f"{case['id']}.html").read_bytes().decode("utf-8")
        pytest.fail(_difference(case["id"], expected, html))


def test_the_generated_templates_match_the_node_sources_they_name() -> None:
    node = Path(
        os.environ.get("LIFEASTRO_NODE_SDK")
        or Path(__file__).resolve().parent.parent.parent / "lifeastroapi-node"
    )
    if not (node / "src" / "pdf" / "shared.ts").is_file():
        pytest.skip(f"no Node SDK source at {node}")
    generated = Path(str(shared.__file__)).parent
    checked = 0
    for path in generated.glob("*.py"):
        lines = path.read_text(encoding="utf-8").splitlines()
        if path.name == "__init__.py":
            continue
        source = node / lines[1].split("lifeastroapi-node/")[1]
        expected = lines[2].split("sha256: ")[1]
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        assert actual == expected, f"{path.name}: run node scripts/generate_pdf.mjs"
        checked += 1
    assert checked == 16


def test_text_helpers_match_node() -> None:
    for row in fixture("text"):
        text = row["s"]
        assert pdf.humanize(text) == row["humanize"], ascii(text)
        assert pdf.esc(text) == row["esc"], ascii(text)
        for locale, expected in row["clean"].items():
            assert pdf.clean_narrative(text, locale) == expected, (locale, ascii(text))


@pytest.mark.parametrize(
    "text",
    [
        "x" + " " * 100_000 + "y",
        "word " * 20_000,
        "\t" * 100_000,
        "जन्म " * 20_000,
        "शास्त्र वैदिक ज्योतिष " * 10_000,  # opens the Hindi filler, without its pivot words
        "In Vedic astrology " * 10_000,  # the same for the English one
        "planet in the house of gains " * 35_000,  # 1 MB
    ],
    ids=["spaces", "no-danda", "tabs", "devanagari", "hindi-opener", "english-opener", "1MB"],
)
def test_long_strings_render_in_linear_time(text: str) -> None:
    started = time.perf_counter()
    pdf.esc_body(text, "hi")
    assert time.perf_counter() - started < 3


def test_brihad_header_footer_and_toc_match_node() -> None:
    golden = fixture("brihad")
    camel = {
        "companyName": "Acme Astro",
        "footerText": "Acme Astro · confidential",
    }
    assert sections.brihadHeaderTemplate() == golden["header"][0]
    assert sections.brihadFooterTemplate() == golden["footer"][0]
    # The first argument is the report's branding, which has PascalCase keys only.
    assert sections.brihadHeaderTemplate(camel) == golden["header"][1]
    assert sections.brihadFooterTemplate(camel) == golden["footer"][1]
    for toc in golden["toc"]:
        assert sections.buildBrihadToc(toc["entries"], toc["heading"]) == toc["html"]
    assert len(golden["toc"]) == 10
    assert sections.buildBrihadToc([], "Table of Contents") == ""
    margin = {"top": "26mm", "bottom": "16mm", "left": "0mm", "right": "0mm"}
    assert margin == sections.BRIHAD_PDF_MARGIN


def test_brihad_section_tagging_matches_node() -> None:
    cases = {case["id"]: case for case in fixture("cases")}
    for tagged in fixture("brihad")["tagged"]:
        case = cases[tagged["id"]]
        html = pdf.render_kundli_brihad_html(case["data"], python_branding(case["branding"]))
        result = sections.tagBrihadSectionsForToc(html)
        assert result["titles"] == tagged["titles"], tagged["id"]
        assert _sha256(result["html"]) == tagged["sha256"], tagged["id"]


def test_report_data_is_escaped() -> None:
    tag = "<img src=x>"
    html = pdf.render_kundli_brihad_html(
        {
            "rajyoga_power": {"percent": 5, "planets": [tag]},
            "kp": {
                "cusps": [{"house": 1}],
                "planet_significators": [{"key": "Sun", "values": [tag]}],
            },
        }
    )
    assert tag not in html
    assert html.count("&lt;img src=x&gt;") == 2


def test_a_logo_url_is_escaped_but_not_humanized() -> None:
    url = "https://cdn.example/a,,b->c.png?x=1&y=2"
    html = pdf.render_kundli_lite_html({}, {"logo_url": url})
    assert 'src="https://cdn.example/a,,b-&gt;c.png?x=1&amp;y=2"' in html


def test_the_footer_takes_every_colour_the_headings_take() -> None:
    html = pdf.render_kundli_lite_html({}, {"secondary_color": "rgb(1 2 3 / 50%)"})
    assert "color: rgb(1 2 3 / 50%);" in html


@pytest.mark.parametrize("name", RENDERERS)
def test_customer_html_has_no_css_comments(name: str) -> None:
    assert "/*" not in renderer(name)({})


def test_a_watermark_may_hold_comment_markers() -> None:
    html = pdf.render_kundli_lite_html({}, {"watermark_text": "A/*B*/C"})
    assert 'content: "A/*B*/C"' in html


def test_numerology_prints_the_top_level_name() -> None:
    html = pdf.render_numerology_html({"name": "Arjun Mehta", "driver": 6})
    assert '<div class="subject">Arjun Mehta</div>' in html
    assert "grid-auto-flow: column" in html


def test_varshaphal_prefers_the_local_solar_return() -> None:
    moment = {"SolarReturnISO": "2027-01-15T16:39:17Z"}
    assert "2027-01-15 16:39 UTC" in pdf.render_varshaphal_html(moment)
    html = pdf.render_varshaphal_html({**moment, "SolarReturnLocal": "2027-01-15 22:09 IST"})
    assert "2027-01-15 22:09 IST" in html
    assert "16:39" not in html


def test_chart_layout_matches_node() -> None:
    charts = fixture("charts")
    assert len(charts) == 1 + 12 * 14
    for chart in charts:
        svg = north_indian_chart.northIndianChartSvg(chart["opts"])
        assert _sha256(svg) == chart["sha256"], chart["opts"]


def test_the_running_header_and_footer_print_in_a_sans_face() -> None:
    sans = "Helvetica Neue, Helvetica, Arial, Liberation Sans, sans-serif"
    for template in (sections.brihadHeaderTemplate(), sections.brihadFooterTemplate()):
        assert f"font-family:{locales.PRINT_MARGIN_FONT_STACK_ATTR};" in template
        assert sans in template
    svg = north_indian_chart.northIndianChartSvg({"lagnaSignIndex": 0, "planets": []})
    assert f'style="font-family:{locales.INDIC_FONT_STACK_ATTR};"' in svg
    assert "Helvetica" not in svg


def test_brihad_gives_the_contents_their_own_pages_without_extra_padding() -> None:
    html = pdf.render_kundli_brihad_html({})
    assert re.search(r"\.toc-section \{[^}]*page-break-after: always", html)
    assert "h2, h3 { padding-top: 0; }" in html


@pytest.mark.parametrize("name", RENDERERS)
@pytest.mark.parametrize("locale", ["toString", "constructor", "__proto__", "hasOwnProperty"])
def test_a_locale_naming_an_object_property_is_english(name: str, locale: str) -> None:
    key = "language" if name == "Horoscope" else "Locale"
    report = {key: locale}
    html = renderer(name)(report)
    assert '<html lang="en">' in html
    assert html == renderer(name)({key: "en"})
    assert report == {key: locale}  # the caller's dict is not changed


@pytest.mark.parametrize(
    "moment",
    [
        "2027-01-15T16:39",
        "2027-01-15T16:39:17",
        "2027-01-15T16:39:17.123456789",
        "2027-01-15 16:39",
        "2027-01-15 16:39:17.5",
        "2027-01-15t16:39",
    ],
)
def test_a_timestamp_without_a_zone_is_utc(moment: str) -> None:
    expected = "2027-01-15 16:39 UTC"
    assert expected in pdf.render_varshaphal_html({"SolarReturnISO": moment})
    assert expected in pdf.render_kundli_lite_html({"GeneratedAt": moment})


def _drawn(html: str) -> tuple[list[Any], list[str]]:
    """What a Brihad draws, whatever its language: each chart's sign numbers and the planets
    (by colour) in their places, and the glyphs of the planet cards."""
    charts = []
    for svg in re.findall(r'<svg viewBox="0 0 100 100".*?</svg>', html, re.DOTALL):
        signs, planets = [], []
        for x, y, weight, body in re.findall(
            r'<text x="([^"]+)" y="([^"]+)"[^>]*?font-weight="(\w+)"[^>]*>(.*?)</text>', svg
        ):
            if weight == "600":
                signs.append((x, y, body))
            else:
                planets += [(x, y, fill) for fill in re.findall(r'<tspan fill="([^"]+)"', body)]
        charts.append((signs, sorted(planets)))
    glyphs = re.findall(r'<div class="graha-card".*?(<svg.*?</svg>)', html, re.DOTALL)
    return charts, glyphs


# (English, Marathi as the API spells it in vedic.PlanetMR)
MARATHI_PLANETS = (
    ("Sun", "सूर्य"),
    ("Moon", "चंद्र"),
    ("Mars", "मंगळ"),
    ("Mercury", "बुध"),
    ("Jupiter", "बृहस्पती"),
    ("Venus", "शुक्र"),
    ("Saturn", "शनी"),
    ("Rahu", "राहू"),
    ("Ketu", "केतू"),
)


@pytest.mark.parametrize("with_name_en", [True, False], ids=["name_en", "localized-name-only"])
def test_marathi_brihad_draws_the_same_planets_as_english(with_name_en: bool) -> None:
    def report(locale: str) -> dict[str, Any]:
        marathi = locale == "mr"
        names = [mr if marathi else en for en, mr in MARATHI_PLANETS]
        planets: list[dict[str, Any]] = []
        for i, ((english, _mr), name) in enumerate(zip(MARATHI_PLANETS, names)):
            planets.append({"name": name, "house_num": i + 1})
            if with_name_en:
                planets[-1]["name_en"] = english
        return {
            "Locale": locale,
            "Ascendant": {"sign": "मेष" if marathi else "Aries"},
            "Planets": planets,
            "DivisionalCharts": [
                {
                    "varga": varga,
                    "lagna_sign": "तूळ" if marathi else "Libra",
                    # The API sends no English name inside divisional charts.
                    "planets": [
                        {"name": name, "house": (i * step) % 12 + 1} for i, name in enumerate(names)
                    ],
                }
                for varga, step in (("D2", 6), ("D3", 5), ("D9", 7))
            ],
        }

    charts, glyphs = _drawn(pdf.render_kundli_brihad_html(report("en")))
    assert len(charts) == 5  # lagna and navamsa, then the three divisional charts
    assert [len(planets) for _signs, planets in charts] == [9] * 5
    assert len(glyphs) == 9
    assert _drawn(pdf.render_kundli_brihad_html(report("mr"))) == (charts, glyphs)


@pytest.mark.skipif(not MANIFEST, reason=f"no shared PDF reference at {PDF_WORK}")
@pytest.mark.parametrize("person", ["mumbai", "chennai", "kolkata"])
@pytest.mark.parametrize("language", ["hi", "mr", "te", "ta", "kn", "ml", "gu", "bn", "pa"])
def test_every_language_draws_the_same_planets_as_english(person: str, language: str) -> None:
    def drawn(lang: str) -> tuple[list[Any], list[str]]:
        path = PDF_WORK / "inputs" / f"{person}.kundli-brihad.{lang}.json"
        return _drawn(pdf.render_kundli_brihad_html(json.loads(path.read_text(encoding="utf-8"))))

    english = drawn("en")
    assert sum(len(planets) for _signs, planets in english[0]) == 153  # 17 charts of 9 planets
    assert drawn(language) == english


def test_toc_headings_cover_the_ten_languages() -> None:
    assert sorted(locales.TOC_HEADING) == sorted(
        ["en", "hi", "mr", "te", "ta", "kn", "ml", "gu", "bn", "pa"]
    )


def test_a4_print_options_match_node() -> None:
    golden = fixture("brihad")["a4"]
    assert golden == pdf.A4_PRINT_OPTIONS


_HASH_ALL = """
import decimal, gzip, hashlib, json, locale, re, sys, time
try:
    locale.setlocale(locale.LC_ALL, "")
except locale.Error:
    pass
if hasattr(time, "tzset"):
    time.tzset()
decimal.getcontext().prec = 3
decimal.getcontext().rounding = decimal.ROUND_FLOOR
from lifeastroapi import pdf
snake = lambda name: re.sub(r"(?<!^)([A-Z])", r"_\\1", name).lower()
wrong = []
for case in json.loads(gzip.decompress(open(sys.argv[1], "rb").read()).decode("utf-8")):
    render = getattr(pdf, "render_" + snake(case["fn"][6:-4]) + "_html")
    branding = case["branding"] and {snake(k): v for k, v in case["branding"].items()}
    if hashlib.sha256(render(case["data"], branding).encode()).hexdigest() != case["sha256"]:
        wrong.append(case["id"])
print(json.dumps(wrong))
"""


@pytest.mark.parametrize(
    ("culture", "zone"),
    [
        ("de_DE.UTF-8", "America/St_Johns"),
        ("ar_SA.UTF-8", "Pacific/Kiritimati"),
        ("tr_TR.UTF-8", "Asia/Kolkata"),
        ("C", "UTC"),
    ],
)
def test_output_ignores_process_culture_time_zone_and_decimal_context(
    culture: str, zone: str
) -> None:
    fixture("cases")
    run = subprocess.run(
        [sys.executable, "-c", _HASH_ALL, str(FIXTURES / "cases.json.gz")],
        env={**os.environ, "LC_ALL": culture, "LANG": culture, "TZ": zone},
        capture_output=True,
        check=True,
    )
    assert json.loads(run.stdout) == []


def test_importing_the_sdk_does_not_load_the_templates() -> None:
    code = (
        "import sys, lifeastroapi\n"
        "assert 'lifeastroapi.pdf' not in sys.modules\n"
        "import lifeastroapi.pdf\n"
        "assert not [m for m in sys.modules if '_templates' in m]\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_rendering_uses_no_process_file_or_network(monkeypatch: pytest.MonkeyPatch) -> None:
    cases = fixture("cases")
    samples = {case["fn"]: case for case in cases}
    for case in samples.values():
        renderer(case["fn"][6:-4])(case["data"])

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("rendering HTML must be pure")

    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr("socket.socket", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)
    for case in samples.values():
        assert renderer(case["fn"][6:-4])(case["data"], BRANDING).startswith("<!doctype html>")


def test_the_client_response_goes_straight_into_the_renderer() -> None:
    case = next(c for c in fixture("cases") if c["fn"] == "renderKundliLiteHtml" and "html" in c)
    client = make_client(Recorder(lambda _request: reply(case["data"])))
    report = client.reports.kundli_lite(
        date="1990-01-15", time="10:30", tz="Asia/Kolkata", lat=19.076, lon=72.8777
    )
    assert pdf.render_kundli_lite_html(report, python_branding(case["branding"])) == case["html"]


def test_the_branding_argument_wins_over_the_report_json() -> None:
    report = {"Branding": {"CompanyName": "Json & Co", "FooterText": "From JSON"}}
    plain = pdf.render_kundli_lite_html(report)
    assert "Json &amp; Co" in plain
    html = pdf.render_kundli_lite_html(report, {"company_name": "Caller <Co>"})
    assert "Caller &lt;Co&gt;" in html
    assert "From JSON" in html
    assert pdf.resolve_branding({"CompanyName": "Json"}, {"footer_text": "Mine"}) == {
        "company_name": "Json",
        "logo_url": "",
        "primary_color": "#1a1a1a",
        "secondary_color": "#666666",
        "footer_text": "Mine",
        "watermark_text": "",
    }


def test_unsafe_branding_is_dropped() -> None:
    html = pdf.render_kundli_lite_html(
        {},
        {
            "logo_url": "file:///etc/passwd",
            "primary_color": "red}body{display:none",
            "watermark_text": 'x"</style><script>',
        },
    )
    assert "file:" not in html
    assert "red}body" not in html
    assert "<script>" not in html


def test_branding_mistakes_are_reported() -> None:
    with pytest.raises(ValueError, match="unknown branding key 'companyName'"):
        pdf.render_kundli_lite_html({}, {"companyName": "Acme"})
    with pytest.raises(TypeError, match="must be a string"):
        pdf.render_kundli_lite_html({}, {"company_name": 7})
    assert pdf.render_kundli_lite_html({}, {"company_name": None}) == pdf.render_kundli_lite_html(
        {}
    )


def test_wrong_input_is_explained() -> None:
    with pytest.raises(TypeError, match="await"):
        pdf.render_kundli_lite_html([])  # type: ignore[arg-type]
