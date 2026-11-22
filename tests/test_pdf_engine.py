"""The engines without a browser: a DevTools stand-in and fake browser programs."""

from __future__ import annotations

import asyncio
import concurrent.futures
import gc
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Callable

import pytest

from lifeastroapi import LifeAstroError, pdf
from lifeastroapi.pdf import _browser, _chrome
from lifeastroapi.pdf._options import css_length_to_inches, printable

from pdf_devtools_stub import DevToolsStub
from pdf_support import outline_titles

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="uses a shell script as browser")


@pytest.fixture
def stub() -> Iterator[DevToolsStub]:
    server = DevToolsStub()
    yield server
    server.close()


@pytest.fixture
def engine(stub: DevToolsStub) -> Iterator[pdf.ChromePdfEngine]:
    with pdf.ChromePdfEngine.connect(stub.url) as connected:
        yield connected


@pytest.fixture
def temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "temp dir"  # with a space, as on Windows and macOS
    directory.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(directory))
    return directory


@pytest.fixture
def fake_browser(tmp_path: Path) -> Callable[[str], Path]:
    def make(body: str) -> Path:
        script = tmp_path / "fake chrome"
        script.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        script.chmod(0o755)
        return script

    return make


def leftovers(directory: Path) -> list[str]:
    return [path.name for path in directory.glob("lifeastro-chrome-*")]


def failure(run: Callable[[], object]) -> pdf.PdfError:
    with pytest.raises(pdf.PdfError) as caught:
        run()
    return caught.value


# -- options -----------------------------------------------------------------


def test_options_geometry() -> None:
    options = pdf.PdfOptions(format="Letter", landscape=True)
    assert options.paper_inches() == (11.0, 8.5)
    assert options.uses_css_page_size()
    assert not pdf.PdfOptions(display_header_footer=True).uses_css_page_size()
    assert not pdf.PdfOptions(prefer_css_page_size=False).uses_css_page_size()
    margin = pdf.PdfMargin(top="25.4mm", bottom="2.54cm", left="1in", right="96px")
    assert margin.inches() == pytest.approx((1, 1, 1, 1))
    assert css_length_to_inches("48") == 0.5
    assert css_length_to_inches(None) == 0


@pytest.mark.parametrize(
    "make",
    [
        lambda: pdf.PdfMargin(top="1 em"),
        lambda: pdf.PdfOptions(format="B4"),  # type: ignore[arg-type]
        lambda: pdf.PdfOptions(scale=3),
        lambda: pdf.PdfOptions(timeout=0),
    ],
)
def test_bad_options_fail_early(make: Callable[[], object]) -> None:
    with pytest.raises(ValueError):
        make()


def test_pdf_error_is_an_sdk_error() -> None:
    error = pdf.PdfError("broken", code="timeout")
    assert isinstance(error, LifeAstroError)
    assert (error.status, error.code) == (0, "timeout")


def test_lone_surrogates_are_replaced() -> None:
    assert printable("a\ud800b\U0001f600") == "a\ufffdb\U0001f600"


# -- DevTools ----------------------------------------------------------------


def test_prints_through_devtools(stub: DevToolsStub, engine: pdf.ChromePdfEngine) -> None:
    options = pdf.PdfOptions(format="Letter", landscape=True, margin=pdf.PdfMargin(top="1in"))
    css = "@page { margin-top: 1in !important; size: 11in 8.5in !important; }\n"
    sent = f"<p>नमस्ते</p>\n<style>{css}</style>"  # what would lose to the page's own CSS
    assert engine.html_to_pdf("<p>नमस्ते</p>", options) == f"%PDF{sent}".encode()
    params = stub.params("Page.printToPDF")
    assert (params["paperWidth"], params["paperHeight"], params["marginTop"]) == (11, 8.5, 1)
    assert params["preferCSSPageSize"] is True
    assert params["landscape"] is False
    assert "headerTemplate" not in params
    assert stub.handshake.startswith(b"GET /devtools/browser/stub?a=1 HTTP/1.1")
    assert b"Host: 127.0.0.1:" in stub.handshake
    assert stub.methods()[-1] == "Target.closeTarget"


def test_header_and_footer(stub: DevToolsStub, engine: pdf.ChromePdfEngine) -> None:
    engine.html_to_pdf("x", pdf.PdfOptions(display_header_footer=True, header_template="<b>H</b>"))
    params = stub.params("Page.printToPDF")
    assert params["headerTemplate"] == "<b>H</b>"
    assert params["footerTemplate"] == "<span></span>"
    assert params["preferCSSPageSize"] is False


@pytest.mark.parametrize("size", [10, 200, 70_000, 2_000_000])
def test_frames_of_every_size_fragments_and_pings(
    stub: DevToolsStub, engine: pdf.ChromePdfEngine, size: int
) -> None:
    stub.fragment = stub.ping = True
    html = "x" * size
    assert engine.html_to_pdf(html) == b"%PDF" + html.encode()
    assert stub.pongs > 0


def test_threads_share_one_engine(stub: DevToolsStub, engine: pdf.ChromePdfEngine) -> None:
    stub.delay = 0.03
    pages = [f"<p>report {i}</p>" for i in range(16)]
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        assert list(pool.map(engine.html_to_pdf, pages)) == [b"%PDF" + p.encode() for p in pages]
    assert stub.connections == 1
    assert stub.methods().count("Target.closeTarget") == len(pages)


@pytest.mark.parametrize("method", ["Page.setDocumentContent", "Runtime.evaluate"])
def test_a_load_timeout_closes_the_tab(
    stub: DevToolsStub, engine: pdf.ChromePdfEngine, method: str
) -> None:
    stub.hang = {method}
    error = failure(lambda: engine.html_to_pdf("x", pdf.PdfOptions(timeout=0.3)))
    assert error.code == "timeout"
    assert "did not finish loading" in error.message
    assert "Target.closeTarget" in stub.methods()


def test_a_print_timeout_closes_the_tab(stub: DevToolsStub, engine: pdf.ChromePdfEngine) -> None:
    stub.hang = {"Page.printToPDF"}
    error = failure(lambda: engine.html_to_pdf("x", pdf.PdfOptions(print_timeout=0.3)))
    assert error.code == "timeout"
    assert "Target.closeTarget" in stub.methods()


def test_cancel_stops_the_job_and_closes_the_tab(
    stub: DevToolsStub, engine: pdf.ChromePdfEngine
) -> None:
    stub.hang = {"Page.printToPDF"}
    stop = threading.Event()

    def cancel_when_printing() -> None:
        stub.wait_for("Page.printToPDF")
        stop.set()

    threading.Thread(target=cancel_when_printing).start()
    started = time.monotonic()
    assert failure(lambda: engine.html_to_pdf("x", cancel=stop)).code == "cancelled"
    assert time.monotonic() - started < 3
    assert "Target.closeTarget" in stub.methods()


def test_already_cancelled_starts_nothing(stub: DevToolsStub, engine: pdf.ChromePdfEngine) -> None:
    stop = threading.Event()
    stop.set()
    assert failure(lambda: engine.html_to_pdf("x", cancel=stop)).code == "cancelled"
    assert "Target.createTarget" not in stub.methods()


def test_a_devtools_error_is_reported(stub: DevToolsStub, engine: pdf.ChromePdfEngine) -> None:
    stub.errors = {"Page.printToPDF": "Printing failed"}
    error = failure(lambda: engine.html_to_pdf("x"))
    assert error.code == "browser_failed"
    assert "Printing failed" in error.message


def test_a_crashed_tab_fails_at_once(stub: DevToolsStub, engine: pdf.ChromePdfEngine) -> None:
    stub.crash = {"Page.printToPDF"}
    assert "crashed" in failure(lambda: engine.html_to_pdf("x")).message


def test_a_lost_browser_is_replaced(stub: DevToolsStub, engine: pdf.ChromePdfEngine) -> None:
    stub.drop = {"Page.printToPDF"}
    assert failure(lambda: engine.html_to_pdf("x")).code == "browser_failed"
    stub.drop.clear()
    assert engine.html_to_pdf("again") == b"%PDFagain"
    assert stub.connections == 2


def test_close_fails_waiting_jobs(stub: DevToolsStub, engine: pdf.ChromePdfEngine) -> None:
    stub.hang = {"Page.printToPDF"}

    def close_when_printing() -> None:
        stub.wait_for("Page.printToPDF")
        engine.close()

    threading.Thread(target=close_when_printing).start()
    assert failure(lambda: engine.html_to_pdf("x")).code == "closed"
    assert failure(lambda: engine.html_to_pdf("x")).code == "closed"
    assert "Browser.close" not in stub.methods()  # a connected browser is left running
    engine.close()


def test_async_does_not_block_the_loop(stub: DevToolsStub, engine: pdf.ChromePdfEngine) -> None:
    stub.delay = 0.2

    async def run() -> None:
        ticks = 0
        job = asyncio.ensure_future(engine.html_to_pdf_async("async"))
        while not job.done():
            await asyncio.sleep(0.01)
            ticks += 1
        assert await job == b"%PDFasync"
        assert ticks > 10

    asyncio.run(run())


def test_cancelling_the_task_stops_the_job(stub: DevToolsStub, engine: pdf.ChromePdfEngine) -> None:
    stub.hang = {"Page.printToPDF"}

    async def run() -> None:
        job = asyncio.ensure_future(pdf.html_to_pdf_async("x", engine=engine))
        while "Page.printToPDF" not in stub.methods():
            await asyncio.sleep(0.01)
        job.cancel()
        with pytest.raises(asyncio.CancelledError):
            await job
        assert "Target.closeTarget" in stub.methods()

    started = time.monotonic()
    asyncio.run(run())
    assert time.monotonic() - started < 5


def test_after_fork_the_child_starts_afresh(stub: DevToolsStub) -> None:
    engine = pdf.ChromePdfEngine.connect(stub.url)
    parent = engine._browser
    assert parent is not None
    engine._after_fork()  # what os.fork runs in the child
    assert engine._browser is None
    assert engine.html_to_pdf("child") == b"%PDFchild"
    assert stub.connections == 2
    engine.close()


# -- finding and starting the browser ----------------------------------------


def test_environment_names_the_browser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _browser.BROWSER_ENV:
        monkeypatch.delenv(name, raising=False)
    browser = tmp_path / ("my chrome.exe" if sys.platform == "win32" else "my chrome")
    browser.write_bytes(b"")
    browser.chmod(0o755)
    monkeypatch.setenv("CHROME_PATH", str(browser))
    assert pdf.find_browser() == str(browser)
    monkeypatch.setenv("LIFEASTRO_CHROME", str(tmp_path / "missing"))
    assert pdf.find_browser() == str(browser)


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("darwin", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        ("linux", "microsoft-edge-stable"),
        (
            "win32",
            os.path.join("C:\\Program Files", "Google", "Chrome", "Application", "chrome.exe"),
        ),
    ],
)
def test_candidates_per_platform(
    monkeypatch: pytest.MonkeyPatch, platform: str, expected: str
) -> None:
    monkeypatch.setenv("PROGRAMFILES", "C:\\Program Files")
    monkeypatch.setattr(sys, "platform", platform)
    assert expected in list(_browser._candidates())


def test_no_browser_says_what_to_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_chrome, "find_browser", lambda: None)
    error = failure(lambda: pdf.html_to_pdf("x"))
    assert error.code == "browser_not_found"
    for hint in (
        "apt-get install chromium fonts-noto-core",
        "Edge",
        "LIFEASTRO_CHROME",
        "Gotenberg",
    ):
        assert hint in error.message


def test_a_wrong_executable_is_reported(temp: Path, tmp_path: Path) -> None:
    engine = pdf.ChromePdfEngine(tmp_path / "no such browser")
    assert failure(lambda: engine.html_to_pdf("x")).code == "browser_not_found"
    assert leftovers(temp) == []


@posix_only
def test_a_browser_that_exits_is_cleaned_up(
    temp: Path, fake_browser: Callable[[str], Path]
) -> None:
    engine = pdf.ChromePdfEngine(fake_browser("echo 'No usable sandbox!' >&2; exit 3"))
    error = failure(lambda: engine.html_to_pdf("x"))
    assert error.code == "browser_failed"
    assert "status 3" in error.message
    assert "No usable sandbox" in error.message
    assert "no_sandbox=True" in error.message
    assert leftovers(temp) == []


@posix_only
def test_a_launch_timeout_kills_the_process_and_its_helpers(
    temp: Path, tmp_path: Path, fake_browser: Callable[[str], Path]
) -> None:
    pids = tmp_path / "pids"
    script = fake_browser(f'sleep 60 &\necho "$$ $!" > "{pids}"\nwait')
    engine = pdf.ChromePdfEngine(script, launch_timeout=1.5)
    assert failure(lambda: engine.html_to_pdf("x")).code == "timeout"
    assert leftovers(temp) == []
    for pid in map(int, pids.read_text().split()):
        deadline = time.monotonic() + 5
        while _running(pid):
            assert time.monotonic() < deadline, f"process {pid} was left running"
            time.sleep(0.05)


def _running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@posix_only
@pytest.mark.parametrize("how", ["cancel", "close"])
def test_a_launch_can_be_stopped(temp: Path, fake_browser: Callable[[str], Path], how: str) -> None:
    engine = pdf.ChromePdfEngine(fake_browser("exec sleep 60"))
    stop = threading.Event()
    threading.Timer(0.3, stop.set if how == "cancel" else engine.close).start()
    started = time.monotonic()
    error = failure(lambda: engine.html_to_pdf("x", cancel=stop))
    assert error.code == ("cancelled" if how == "cancel" else "closed")
    assert time.monotonic() - started < 10
    assert leftovers(temp) == []


@posix_only
@pytest.mark.parametrize(
    ("uid", "given", "expected"),
    [(1000, None, False), (0, None, True), (0, False, False), (1000, True, True)],
)
def test_no_sandbox_is_never_silent(
    temp: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_browser: Callable[[str], Path],
    uid: int,
    given: bool | None,
    expected: bool,
) -> None:
    seen = tmp_path / "args"
    script = fake_browser(f'printf "%s\\n" "$@" > "{seen}"; exit 1')
    monkeypatch.setattr(os, "geteuid", lambda: uid)
    failure(lambda: pdf.ChromePdfEngine(script, no_sandbox=given).launch())
    args = seen.read_text().splitlines()
    assert ("--no-sandbox" in args) is expected
    assert "--headless=new" in args
    profile = next(arg for arg in args if arg.startswith("--user-data-dir="))
    assert profile.startswith(f"--user-data-dir={temp}{os.sep}lifeastro-chrome-")


@posix_only
@pytest.mark.parametrize("how", ["close", "garbage", "port-file"])
def test_a_started_browser_is_stopped_and_its_profile_removed(
    temp: Path, stub: DevToolsStub, fake_browser: Callable[[str], Path], how: str
) -> None:
    port = stub.url.split(":")[2].split("/")[0]
    if how == "port-file":  # as on Windows, where the browser may print nothing
        path = "/devtools/browser/00000000-0000-4000-8000-000000000000"
        announce = (
            'for a in "$@"; do case "$a" in --user-data-dir=*) d="${a#*=}";; esac; done\n'
            f'mkdir -p "$d"; printf "{port}\\n{path}" > "$d/DevToolsActivePort"'
        )
    else:
        announce = f"echo 'DevTools listening on {stub.url}' >&2"
    engine = pdf.ChromePdfEngine(fake_browser(announce + "\nexec sleep 2")).launch()
    assert engine.html_to_pdf("x") == b"%PDFx"
    assert len(leftovers(temp)) == 1
    if how == "garbage":
        del engine
        gc.collect()
    else:
        engine.close()
    assert "Browser.close" in stub.methods()
    assert leftovers(temp) == []


def test_windows_processes_are_killed_by_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[list[str]] = []

    class Process:
        pid = 4242
        returncode = None

        def poll(self) -> None:
            return None

        def kill(self) -> None:
            pass

        def wait(self, timeout: float) -> int:
            return 1

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, "run", lambda command, **_options: ran.append(command))
    process: Any = Process()
    _browser._kill(process)
    assert ran == [["taskkill", "/PID", "4242", "/T", "/F"]]


def test_brihad_second_print_has_branding_pages_and_no_markers() -> None:
    printed: list[tuple[str, pdf.PdfOptions | None]] = []

    class OnePagePerSection:
        """Prints a PDF with one page per linked marker, after a cover and a contents page."""

        def html_to_pdf(
            self,
            html: str,
            options: pdf.PdfOptions | None = None,
            *,
            cancel: threading.Event | None = None,
        ) -> bytes:
            printed.append((html, options))
            urls = re.findall(r'<a href="(https://toc\.lifeastroapi\.invalid/T[0-9]+)"', html)
            return _pdf_with_links(["", "", *urls])

    report = {
        "Locale": "ml",
        "Branding": {"CompanyName": "Json Co", "FooterText": "Json footer"},
        "Ascendant": {"sign": "മേടം"},
        "Planets": [{"name": "Sun", "house_num": 1}],
    }
    data = pdf.kundli_brihad_pdf(report, {"company_name": "Acme"}, engine=OnePagePerSection())

    (first, _options), (final, options) = printed
    assert "⟦T0⟧" in first
    assert "⟦T" not in final
    assert '<span style="color:#fff;font-size:1px;">&nbsp;</span>' in final
    assert options is not None
    assert "Acme" in str(options.header_template)  # the caller's field
    assert "Json footer" in str(options.footer_template)  # the report's, where the caller has none
    pages = [int(n) for n in re.findall(r'class="toc-page"[^>]*>(\d+)</span>', final)]
    assert pages == list(range(3, 3 + len(pages)))
    titles = outline_titles(data)
    assert len(titles) == len(pages) > 1
    assert any("\u0d00" <= char <= "\u0d7f" for char in titles[0])  # still Malayalam
    assert b"/Info 99 0 R" in data.split(b"trailer")[-1]


@pytest.mark.parametrize("locale", ["toString", "constructor", "__proto__"])
def test_brihad_contents_of_an_object_property_locale_are_english(locale: str) -> None:
    printed: list[str] = []

    class OnePagePerSection:
        def html_to_pdf(
            self,
            html: str,
            options: pdf.PdfOptions | None = None,
            *,
            cancel: threading.Event | None = None,
        ) -> bytes:
            printed.append(html)
            assert options is not None
            assert "Helvetica Neue" in str(options.header_template)
            assert "Helvetica Neue" in str(options.footer_template)
            return _pdf_with_links(["", *re.findall(r'<a href="(https://toc\.[^"]+)"', html)])

    report = {"Locale": locale, "Planets": [{"name": "Sun", "house_num": 1}]}
    pdf.kundli_brihad_pdf(report, engine=OnePagePerSection())
    assert '<html lang="en">' in printed[-1]
    assert '<div class="toc-banner">Table of Contents</div>' in printed[-1]


def _pdf_with_links(urls: list[str]) -> bytes:
    """A PDF with one page for each URL, linked to it when it is not empty."""
    out = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    for index, url in enumerate(urls):
        link = b"<< /Subtype /Link /A << /S /URI /URI (%s) >> >>" % url.encode()
        annots = b" /Annots [%d 0 R]" % (200 + index) if url else b""
        out += b"%d 0 obj\n<< /Type /Page%s >>\nendobj\n" % (100 + index, annots)
        if url:
            out += b"%d 0 obj\n%s\nendobj\n" % (200 + index, link)
    out += b"99 0 obj\n<< /Title (Report) >>\nendobj\n"
    return out + b"trailer\n<< /Root 1 0 R /Info 99 0 R >>\nstartxref\n0\n%%EOF\n"


def test_one_call_functions_use_the_engine_given() -> None:
    class Recording:
        def __init__(self) -> None:
            self.html: list[str] = []
            self.options: list[pdf.PdfOptions | None] = []

        def html_to_pdf(
            self,
            html: str,
            options: pdf.PdfOptions | None = None,
            *,
            cancel: threading.Event | None = None,
        ) -> bytes:
            self.html.append(html)
            self.options.append(options)
            return b"%PDF-recorded"

    engine = Recording()
    names = [name for name in pdf.__all__ if name.endswith("_pdf") and name != "html_to_pdf"]
    assert len(names) == 10
    for name in names:
        assert getattr(pdf, name)({}, engine=engine) == b"%PDF-recorded"
        made = asyncio.run(getattr(pdf, f"{name}_async")({}, engine=engine))
        assert made == b"%PDF-recorded"
    assert all(html.startswith("<!doctype html>") for html in engine.html)
