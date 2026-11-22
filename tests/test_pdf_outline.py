"""Bookmarks and link reading (``lifeastroapi.pdf._outline``)."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from lifeastroapi.pdf import OutlineItem, PdfError, add_pdf_outline
from lifeastroapi.pdf._outline import link_target_pages, page_count

from pdf_support import fixture, outline_titles, qpdf_outline_titles


def small_pdf(*objects: bytes, pages: int = 3) -> bytes:
    kids = b" ".join(b"%d 0 R" % (3 + i) for i in range(pages))
    bodies = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, pages),
        *objects,
    ]
    if not objects:
        bodies += [b"<< /Type /Page /Parent 2 0 R >>"] * pages
    out = b"%PDF-1.4\n"
    for number, body in enumerate(bodies, start=1):
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    return out + b"trailer\n<< /Root 1 0 R >>\nstartxref\n0\n%%EOF\n"


def test_outline_bytes_match_node() -> None:
    goldens = fixture("brihad")["outlines"]
    assert len(goldens) == 2  # without and with document information
    for golden in goldens:
        items = [OutlineItem(i["title"], i["page"], i["level"]) for i in golden["items"]]
        result = add_pdf_outline(base64.b64decode(golden["pdf"]), items)
        assert result == base64.b64decode(golden["result"])


MALAYALAM = "ഭാഗം 1: ലഗ്നം, ഗ്രഹസ്ഥിതി (D1)"


@pytest.mark.parametrize("title", [MALAYALAM, "ਊਠ ਕ", "ऍ ॊ \\ (x)", "മ\r\nഗ"])
def test_titles_with_cr_and_lf_bytes_keep_their_script(title: str) -> None:
    assert outline_titles(add_pdf_outline(small_pdf(), [OutlineItem(title, 1)])) == [title]


def test_qpdf_reads_a_malayalam_title_back(tmp_path: Path) -> None:
    source = base64.b64decode(fixture("brihad")["outlines"][1]["pdf"])
    path = tmp_path / "outline.pdf"
    path.write_bytes(add_pdf_outline(source, [OutlineItem(MALAYALAM, 2)]))
    assert qpdf_outline_titles(path) == [MALAYALAM]


def test_document_information_is_carried_into_the_new_trailer() -> None:
    plain, informed = (base64.b64decode(g["pdf"]) for g in fixture("brihad")["outlines"])
    assert b"/Info 6 0 R" in add_pdf_outline(informed, [OutlineItem("A", 1)]).split(b"trailer")[-1]
    assert b"/Info" not in add_pdf_outline(plain, [OutlineItem("A", 1)])


def test_binary_streams_are_left_as_they_are() -> None:
    stream = b"<< /Length 256 >>\nstream\n" + bytes(range(256)) + b"\nendstream"
    pdf = small_pdf(b"<< /Type /Page /Parent 2 0 R >>", stream, pages=1)
    out = add_pdf_outline(pdf, [OutlineItem("A", 1)])
    assert out.startswith(pdf)
    assert b"/Dest [3 0 R /Fit]" in out


def test_outline_tree_is_appended() -> None:
    pdf = small_pdf()
    items = [
        OutlineItem("Part 1", 1),
        OutlineItem("A (D1)", 1, 2),
        OutlineItem("Deeper", 2, 3),
        OutlineItem("Part 2", 99),
    ]
    out = add_pdf_outline(pdf, items)
    assert out.startswith(pdf)
    assert page_count(out) >= 3
    assert b"/PageMode /UseOutlines" in out
    assert b"<< /Type /Outlines /First 7 0 R /Last 10 0 R /Count 4 >>" in out
    assert b"/First 8 0 R /Last 8 0 R /Count 2" in out
    assert b"\x00\\(" in out  # a parenthesis in a title is escaped
    assert b"/Dest [5 0 R /Fit]" in out  # page 99 is clamped to the last page


def test_empty_outlines_change_nothing() -> None:
    pdf = small_pdf()
    assert add_pdf_outline(pdf, []) == pdf
    assert add_pdf_outline(pdf, [OutlineItem("  ", 1)]) == pdf


@pytest.mark.parametrize("broken", [b"not a pdf", b"trailer << /Root 1 0 R >>"])
def test_unreadable_pdf_raises(broken: bytes) -> None:
    with pytest.raises(PdfError) as caught:
        add_pdf_outline(broken, [OutlineItem("A", 1)])
    assert caught.value.code == "invalid_pdf"


def test_link_target_pages_first_page_wins() -> None:
    link = b"<< /Subtype /Link /A << /S /URI /URI (https://toc.example/%s) >> >>"
    pdf = small_pdf(
        b"<< /Type /Page /Annots [5 0 R] >>",
        b"<< /Type /Page /Annots 7 0 R >>",
        link % b"T0",
        link % b"T\\(1\\)",
        b"[5 0 R 6 0 R]",
        pages=2,
    )
    assert link_target_pages(pdf) == {"https://toc.example/T0": 1, "https://toc.example/T(1)": 2}
