"""Dependency-free post-processing of Chromium PDFs.

A port of the Node SDK's ``src/pdf/outline.ts``, plus the link reader the PHP and Dart
SDKs use to find the page of each Brihad section. Both expect what Chromium writes: a
cross-reference table and uncompressed object dictionaries.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from . import _js
from ._options import PdfError

_OBJECT = re.compile(rb"(?<![0-9])(\d+)\s+0\s+obj(.*?)endobj", re.DOTALL)
_OBJECT_START = re.compile(rb"(?<![0-9])(\d+)\s+0\s+obj\b")
_ROOT = re.compile(rb"/Root\s+(\d+)\s+0\s+R")
_INFO = re.compile(rb"/Info\s+(\d+)\s+0\s+R")
_PAGE = re.compile(rb"/Type\s*/Page\b")
_PAGES = re.compile(rb"/Type\s*/Pages\b")
_START_XREF = re.compile(rb"startxref\s+(\d+)")
_ANNOTS_INLINE = re.compile(rb"/Annots\s*\[([^\]]*)\]")
_ANNOTS_REF = re.compile(rb"/Annots\s+(\d+)\s+0\s+R")
_IN_BRACKETS = re.compile(rb"\[([^\]]*)\]")
_REF = re.compile(rb"(\d+)\s+0\s+R")
_URI = re.compile(rb"/URI\s*\(((?:\\.|[^\\)])*)\)", re.DOTALL)


@dataclass(frozen=True)
class OutlineItem:
    """One PDF bookmark."""

    title: str
    page: int
    """1-based page the bookmark opens."""
    level: int = 1
    """1-based depth: a level 2 item sits under the last level 1 item before it."""


@dataclass(frozen=True)
class _Pdf:
    max_object: int
    root: int
    info: int | None
    pages: list[int]
    start_xref: int
    objects: dict[int, bytes]


def _parse(pdf: bytes) -> _Pdf:
    # Only the last trailer: binary streams before it can hold any bytes.
    trailer = max(0, pdf.rfind(b"trailer"))
    root = _ROOT.search(pdf, trailer)
    info = _INFO.search(pdf, trailer)
    if root is None:
        raise PdfError("PDF: /Root not found in the trailer", code="invalid_pdf")
    objects: dict[int, bytes] = {}
    pages: list[int] = []
    for found in _OBJECT.finditer(pdf):
        number, body = int(found.group(1)), found.group(2)
        objects[number] = body
        if _PAGE.search(body) and not _PAGES.search(body):
            pages.append(number)
    if not pages:
        raise PdfError("PDF: no /Type /Page objects found", code="invalid_pdf")
    start_xref = 0
    for found in _START_XREF.finditer(pdf):
        start_xref = int(found.group(1))
    highest = max((int(m.group(1)) for m in _OBJECT_START.finditer(pdf)), default=0)
    return _Pdf(
        highest,
        int(root.group(1)),
        int(info.group(1)) if info else None,
        pages,
        start_xref,
        objects,
    )


def page_count(pdf: bytes) -> int:
    return len(_parse(pdf).pages)


def link_target_pages(pdf: bytes) -> dict[str, int]:
    """The 1-based page of every URI link. The first page wins for a repeated URI."""
    parsed = _parse(pdf)
    out: dict[str, int] = {}
    for number, page in enumerate(parsed.pages, start=1):
        body = parsed.objects.get(page, b"")
        inline = _ANNOTS_INLINE.search(body)
        refs = inline.group(1) if inline else None
        if refs is None:
            indirect = _ANNOTS_REF.search(body)
            if indirect is not None:
                array = _IN_BRACKETS.search(parsed.objects.get(int(indirect.group(1)), b""))
                refs = array.group(1) if array else None
        if refs is None:
            continue
        annotations = [parsed.objects.get(int(ref), b"") for ref in _REF.findall(refs)]
        if b"<<" in refs:
            annotations.append(refs)
        for annotation in annotations:
            for raw in _URI.findall(annotation):
                uri = re.sub(rb"\\(.)", rb"\1", raw, flags=re.DOTALL)
                out.setdefault(uri.decode("utf-8", "replace"), number)
    return out


def _pdf_text(text: str) -> bytes:
    """UTF-16BE with a BOM, as a PDF literal string."""
    raw = b"\xfe\xff" + text.encode("utf-16-be", "surrogatepass")
    for special in (b"\\", b"(", b")"):
        raw = raw.replace(special, b"\\" + special)
    # A reader takes a bare CR in a literal for LF, which turns Malayalam (U+0Dxx) into Gurmukhi.
    raw = raw.replace(b"\r", b"\\r").replace(b"\n", b"\\n")
    return b"(" + raw + b")"


def _ref(number: int) -> bytes:
    return b"%d 0 R" % number


def add_pdf_outline(pdf: bytes, items: Sequence[OutlineItem]) -> bytes:
    """Add bookmarks to a PDF printed by Chromium and return the new bytes.

    The original bytes are kept; new objects and a cross-reference section are appended.

    :raises PdfError: The PDF cannot be read.
    """
    if not items:
        return pdf
    parsed = _parse(pdf)
    last_page = len(parsed.pages)
    kept = [
        OutlineItem(item.title, max(1, min(int(item.page), last_page)), max(1, item.level))
        for item in items
        if _js.trim(item.title)
    ]
    if not kept:
        return pdf

    outline = parsed.max_object + 1

    def number_of(index: int) -> int:
        return outline + 1 + index

    parents: list[int] = []
    children: list[list[int]] = [[] for _ in kept]
    top: list[int] = []
    stack: list[int] = []
    for index, item in enumerate(kept):
        while stack and kept[stack[-1]].level >= item.level:
            stack.pop()
        parents.append(stack[-1] if stack else -1)
        (children[stack[-1]] if stack else top).append(index)
        stack.append(index)

    open_below = [0] * len(kept)
    for index in range(len(kept) - 1, -1, -1):
        open_below[index] = sum(1 + open_below[child] for child in children[index])

    bodies: dict[int, bytes] = {
        outline: b"<< /Type /Outlines /First %s /Last %s /Count %d >>"
        % (_ref(number_of(top[0])), _ref(number_of(top[-1])), len(kept))
    }
    for family, parent in [(top, -1), *((kids, i) for i, kids in enumerate(children))]:
        for position, index in enumerate(family):
            item = kept[index]
            body = b"<< /Title " + _pdf_text(item.title)
            body += b" /Parent " + _ref(outline if parent < 0 else number_of(parent))
            if position > 0:
                body += b" /Prev " + _ref(number_of(family[position - 1]))
            if position < len(family) - 1:
                body += b" /Next " + _ref(number_of(family[position + 1]))
            kids = children[index]
            if kids:
                body += b" /First %s /Last %s /Count %d" % (
                    _ref(number_of(kids[0])),
                    _ref(number_of(kids[-1])),
                    open_below[index],
                )
            body += b" /Dest [" + _ref(parsed.pages[item.page - 1]) + b" /Fit] >>"
            bodies[number_of(index)] = body

    # The Catalog again, with /Outlines, and /PageMode so the sidebar opens.
    root = re.search(rb"(?<![0-9])%d\s+0\s+obj(.*?)endobj" % parsed.root, pdf, re.DOTALL)
    if root is None:
        raise PdfError("PDF: could not read the /Root object", code="invalid_pdf")
    catalog = root.group(1).strip()
    catalog = re.sub(rb"/Outlines\s+\d+\s+0\s+R", b"", catalog)
    catalog = re.sub(rb"/PageMode\s*/\w+", b"", catalog)
    end = catalog.rfind(b">>")
    if end < 0:
        raise PdfError("PDF: the /Root object is not a dictionary", code="invalid_pdf")
    bodies[parsed.root] = (
        catalog[:end] + b" /Outlines %s /PageMode /UseOutlines " % _ref(outline) + catalog[end:]
    )

    out = bytearray(pdf)
    out += b"\n"
    numbers = sorted(bodies)
    offsets: dict[int, int] = {}
    for number in numbers:
        offsets[number] = len(out)
        out += b"%d 0 obj\n%s\nendobj\n" % (number, bodies[number])

    xref_at = len(out)
    out += b"xref\n"
    start = 0
    while start < len(numbers):
        stop = start + 1
        while stop < len(numbers) and numbers[stop] == numbers[stop - 1] + 1:
            stop += 1
        out += b"%d %d\n" % (numbers[start], stop - start)
        for number in numbers[start:stop]:
            out += b"%010d 00000 n \n" % offsets[number]
        start = stop
    # The last trailer replaces the earlier one, so the document information is carried over.
    information = b" /Info " + _ref(parsed.info) if parsed.info is not None else b""
    out += b"trailer\n<< /Size %d /Root %s%s /Prev %d >>\n" % (
        numbers[-1] + 1,
        _ref(parsed.root),
        information,
        parsed.start_xref,
    )
    out += b"startxref\n%d\n%%%%EOF\n" % xref_at
    return bytes(out)
