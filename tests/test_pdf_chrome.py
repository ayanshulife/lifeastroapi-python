"""HTML to PDF with a real headless browser. Skipped when none is installed."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from lifeastroapi import pdf
from lifeastroapi.pdf import _reports
from lifeastroapi.pdf._outline import link_target_pages, page_count

from pdf_support import (
    RENDERERS,
    example,
    fixture,
    outline_titles,
    python_branding,
    qpdf_outline_titles,
    snake,
)

pytestmark = pytest.mark.skipif(
    pdf.find_browser() is None,
    reason="no Chrome, Chromium or Edge installed (set LIFEASTRO_CHROME to point at one)",
)


@pytest.fixture(scope="module")
def engine() -> Iterator[pdf.ChromePdfEngine]:
    with pdf.ChromePdfEngine() as launched:
        yield launched


def assert_qpdf_ok(data: bytes, tmp_path: Path) -> None:
    qpdf = shutil.which("qpdf")
    if qpdf is None:
        return
    path = tmp_path / "out.pdf"
    path.write_bytes(data)
    run = subprocess.run([qpdf, "--check", str(path)], capture_output=True, check=False)
    assert run.returncode == 0, run.stdout + run.stderr


@pytest.mark.parametrize("name", RENDERERS)
def test_every_report_prints(name: str, engine: pdf.ChromePdfEngine, tmp_path: Path) -> None:
    case = [c for c in fixture("cases") if c["fn"] == f"render{name}Html"][-1]
    make = getattr(pdf, f"{snake(name)}_pdf")
    data = make(case["data"], python_branding(case["branding"]), engine=engine)
    assert data.startswith(b"%PDF-")
    assert page_count(data) >= 1
    assert_qpdf_ok(data, tmp_path)


def test_paper_size_margins_and_landscape(engine: pdf.ChromePdfEngine) -> None:
    options = pdf.PdfOptions(
        format="Letter", landscape=True, margin=pdf.PdfMargin(top="10mm", bottom="1cm")
    )
    data = engine.html_to_pdf("<!doctype html><p>x</p>", options)
    assert b"/MediaBox [0 0 792 612]" in data


def test_link_annotations_give_the_page_of_each_marker(
    engine: pdf.ChromePdfEngine, tmp_path: Path
) -> None:
    html = "<!doctype html>"
    for index, title in enumerate(("पहला", "Second", "తెలుగు")):
        html += (
            f'<section style="page-break-before:always"><h1>{title}</h1>'
            f'<a href="https://toc.lifeastroapi.invalid/T{index}">T{index}</a></section>'
        )
    data = engine.html_to_pdf(html)
    expected = {f"https://toc.lifeastroapi.invalid/T{index}": index + 1 for index in range(3)}
    assert link_target_pages(data) == expected
    items = [pdf.OutlineItem("भाग 1", 1), pdf.OutlineItem("Planets (D1)", 2, 2)]
    assert_qpdf_ok(pdf.add_pdf_outline(data, items), tmp_path)


@pytest.mark.parametrize("locale", ["hi", "ml"])
def test_brihad_toc_numbers_are_the_real_pages(
    locale: str, engine: pdf.ChromePdfEngine, tmp_path: Path
) -> None:
    printed: list[tuple[str, pdf.PdfOptions | None]] = []

    class Recording:
        def html_to_pdf(
            self,
            html: str,
            options: pdf.PdfOptions | None = None,
            *,
            cancel: threading.Event | None = None,
        ) -> bytes:
            printed.append((html, options))
            return engine.html_to_pdf(html, options, cancel=cancel)

    data = pdf.kundli_brihad_pdf(
        example("KundliBrihad", locale),
        {"company_name": "Acme & Co", "footer_text": "Acme Astro"},
        options=pdf.PdfOptions(timeout=120),
        engine=Recording(),
    )
    assert b"/Type /Outlines" in data
    assert page_count(data) > 10
    assert link_target_pages(data) == {}  # the marker links are only in the first print
    assert_qpdf_ok(data, tmp_path)

    assert len(printed) == 2
    final, options = printed[-1]
    assert options is not None
    assert "Acme &amp; Co" in str(options.header_template)
    assert "Acme Astro" in str(options.footer_template)
    listed = [int(n) for n in re.findall(r'class="toc-page"[^>]*>(\d+)</span>', final)]
    # The final document again, with its hidden markers made links: those are the real pages.
    spans = iter(range(len(listed)))
    linked = re.sub(
        '(<span style="color:#fff;font-size:1px;">)&nbsp;</span>',
        lambda m: f'{m.group(1)}<a href="{_reports._MARKER_URL}{next(spans)}">&nbsp;</a></span>',
        final,
    )
    real = link_target_pages(engine.html_to_pdf(linked, options))
    assert listed == [real[f"{_reports._MARKER_URL}{i}"] for i in range(len(listed))]
    # Part 1 opens a page of its own, after the cover and the pages of the contents.
    contents, _, rest = final.partition('<section class="section first"')
    cover_and_contents = engine.html_to_pdf(contents + "</body></html>", options)
    assert rest
    assert listed[0] == page_count(cover_and_contents) + 1
    assert len(listed) > 5


def test_malayalam_brihad_reads_back(engine: pdf.ChromePdfEngine, tmp_path: Path) -> None:
    report = example("KundliBrihad", "ml")
    path = tmp_path / "brihad.pdf"
    path.write_bytes(
        pdf.kundli_brihad_pdf(report, engine=engine, options=pdf.PdfOptions(timeout=120))
    )
    pdfinfo, pdftotext = shutil.which("pdfinfo"), shutil.which("pdftotext")
    if pdfinfo and pdftotext:
        info = subprocess.run([pdfinfo, str(path)], capture_output=True, check=True).stdout
        title = re.search(rb"^Title:[ \t]+(\S.*)$", info, re.MULTILINE)
        assert title is not None, "the outline update dropped the document information"
        assert re.search("[\u0d00-\u0d7f]", title.group(1).decode("utf-8"))
        text = subprocess.run([pdftotext, str(path), "-"], capture_output=True, check=True).stdout
        assert "⟦T".encode() not in text
    titles = qpdf_outline_titles(path)
    assert titles == outline_titles(path.read_bytes())
    for title_text in titles:
        assert not re.search("[\u0a00-\u0a7f]", title_text), title_text  # no Gurmukhi
    assert re.search("[\u0d00-\u0d7f]", titles[0])


def test_concurrent_jobs(engine: pdf.ChromePdfEngine) -> None:
    async def run() -> None:
        report = example("KundliLite", "pa")
        jobs = [pdf.kundli_lite_pdf_async(report, engine=engine) for _ in range(6)]
        ticks = 0
        everything = asyncio.gather(*jobs)
        while not everything.done():
            await asyncio.sleep(0.01)
            ticks += 1
        assert all(data.startswith(b"%PDF-") for data in await everything)
        assert ticks > 3

    asyncio.run(run())


def test_a_page_that_never_loads_times_out(engine: pdf.ChromePdfEngine) -> None:
    html = "<script>addEventListener('load', () => { for (;;) {} })</script>"
    started = time.monotonic()
    with pytest.raises(pdf.PdfError) as caught:
        engine.html_to_pdf(html, pdf.PdfOptions(timeout=1.5))
    assert caught.value.code == "timeout"
    assert time.monotonic() - started < 10
    assert engine.html_to_pdf("<p>still works</p>").startswith(b"%PDF-")


def test_one_call_cleans_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    assert pdf.html_to_pdf("<p>x</p>").startswith(b"%PDF-")
    assert list(tmp_path.glob("lifeastro-chrome-*")) == []


_EXIT = """
from lifeastroapi.pdf import ChromePdfEngine
engine = ChromePdfEngine().launch()
print(engine._browser.pid, engine._browser.directory, flush=True)
"""


def test_interpreter_exit_stops_the_browser() -> None:
    run = subprocess.run([sys.executable, "-c", _EXIT], capture_output=True, text=True, check=True)
    pid, directory = run.stdout.strip().split(" ", 1)
    assert not os.path.exists(directory)
    if sys.platform != "win32":
        with pytest.raises(OSError):
            os.kill(int(pid), 0)


_FORK = """
import os, warnings
warnings.simplefilter("ignore")
from lifeastroapi.pdf import ChromePdfEngine
engine = ChromePdfEngine()
assert engine.html_to_pdf("<p>parent</p>").startswith(b"%PDF")
parent = engine._browser.pid
child = os.fork()
if child == 0:
    ok = engine.html_to_pdf("<p>child</p>").startswith(b"%PDF") and engine._browser.pid != parent
    engine.close()
    os._exit(0 if ok else 1)
assert os.waitpid(child, 0)[1] == 0
assert engine.html_to_pdf("<p>parent</p>").startswith(b"%PDF") and engine._browser.pid == parent
engine.close()
"""


@pytest.mark.skipif(not hasattr(os, "fork"), reason="no fork on this platform")
def test_an_engine_made_before_fork_works_in_both_processes() -> None:
    subprocess.run([sys.executable, "-c", _FORK], check=True, timeout=90)


_CHILD = """
import multiprocessing, os, sys, warnings
warnings.simplefilter("ignore")
from lifeastroapi.pdf import ChromePdfEngine

def work(queue):
    global kept
    kept = ChromePdfEngine().launch()  # never closed
    queue.put((kept._browser.pid, kept._browser.directory))

if __name__ == "__main__":
    context = multiprocessing.get_context(sys.argv[1])
    queue = context.Queue()
    child = context.Process(target=work, args=(queue,))
    child.start()
    pid, directory = queue.get(timeout=60)
    child.join(30)
    assert child.exitcode == 0
    assert not os.path.exists(directory), directory
"""


@pytest.mark.parametrize("method", ["fork", "spawn"])
def test_a_multiprocessing_child_stops_its_browser(method: str, tmp_path: Path) -> None:
    if method == "fork" and not hasattr(os, "fork"):
        pytest.skip("no fork on this platform")
    script = tmp_path / "child.py"
    script.write_text(_CHILD, encoding="utf-8")
    subprocess.run([sys.executable, str(script), method], check=True, timeout=120)


_TERMINATED = """
import signal, sys, time
from lifeastroapi.pdf import ChromePdfEngine
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # as the README says
engine = ChromePdfEngine().launch()
print(engine._browser.directory, flush=True)
if sys.argv[1] == "printing":
    engine.html_to_pdf("<script>addEventListener('load', () => { for (;;) {} })</script>")
time.sleep(60)
"""


@pytest.mark.skipif(sys.platform == "win32", reason="no SIGTERM on Windows")
@pytest.mark.parametrize("state", ["idle", "printing"])
def test_sigterm_with_the_documented_handler_stops_the_browser(state: str) -> None:
    command = [sys.executable, "-c", _TERMINATED, state]
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True) as process:
        assert process.stdout is not None
        directory = process.stdout.readline().strip()
        time.sleep(1)
        process.terminate()
        assert process.wait(timeout=30) == 0
    assert directory
    assert not os.path.exists(directory)
