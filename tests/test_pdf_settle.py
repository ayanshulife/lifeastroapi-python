"""Closing, cancelling and crashes: every call settles with a PDF or a PdfError.

Nothing may reach the caller's event loop or ``threading.excepthook``, and no browser or
profile may be left behind.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import gc
import os
import signal
import socket
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Callable

import pytest

from lifeastroapi import pdf

from pdf_devtools_stub import DevToolsStub

#: ``SIGKILL``, which Windows lacks (those tests are skipped there).
KILL: int = getattr(signal, "SIGKILL", signal.SIGTERM)
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="uses signals and shell scripts")
needs_browser = pytest.mark.skipif(
    pdf.find_browser() is None,
    reason="no Chrome, Chromium or Edge installed (set LIFEASTRO_CHROME to point at one)",
)
#: Keeps a real tab busy, so that the jobs are still running when the test closes or kills.
BUSY = (
    "<script>addEventListener('load', () => "
    "{ const end = Date.now() + 20000; while (Date.now() < end); })</script>"
)


@pytest.fixture
def stub() -> Iterator[DevToolsStub]:
    server = DevToolsStub()
    yield server
    server.close()


@pytest.fixture
def temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    return tmp_path


@pytest.fixture
def noise(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What would surface in the caller's app instead of in the awaited call."""
    seen: list[str] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: seen.append(repr(args.exc_value)))
    monkeypatch.setattr(sys, "unraisablehook", lambda args: seen.append(repr(args.exc_value)))
    return seen


def listen(noise: list[str]) -> None:
    asyncio.get_running_loop().set_exception_handler(
        lambda _loop, context: noise.append(str(context))
    )


def codes(results: list[Any]) -> set[str]:
    out = set()
    for result in results:
        if isinstance(result, pdf.PdfError):
            out.add(result.code)
        else:
            assert isinstance(result, bytes), repr(result)
            out.add("pdf")
    return out


def wait_until(what: Callable[[], bool], seconds: float = 8.0) -> None:
    deadline = time.monotonic() + seconds
    while not what():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.02)


def running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def profiles(directory: Path) -> list[Path]:
    return list(directory.glob("lifeastro-chrome-*"))


def print_in_threads(
    engine: pdf.ChromePdfEngine, html: str, count: int, then: Callable[[], None]
) -> list[Any]:
    def one(_index: int) -> Any:
        try:
            return engine.html_to_pdf(html, pdf.PdfOptions(timeout=15, print_timeout=15))
        except Exception as error:
            return error

    with concurrent.futures.ThreadPoolExecutor(count) as pool:
        jobs = [pool.submit(one, index) for index in range(count)]
        then()
        return [job.result() for job in jobs]


# -- close -------------------------------------------------------------------


def test_close_settles_every_sync_print(stub: DevToolsStub, noise: list[str]) -> None:
    stub.hang = {"Page.printToPDF"}
    engine = pdf.ChromePdfEngine.connect(stub.url)

    def close() -> None:
        wait_until(lambda: stub.methods().count("Page.printToPDF") == 6)
        engine.close()

    assert codes(print_in_threads(engine, "x", 6, close)) == {"closed"}
    gc.collect()
    assert noise == []


def test_close_settles_every_async_print(stub: DevToolsStub, noise: list[str]) -> None:
    stub.hang = {"Page.printToPDF"}
    engine = pdf.ChromePdfEngine.connect(stub.url)

    async def run() -> list[Any]:
        listen(noise)
        jobs = [asyncio.ensure_future(engine.html_to_pdf_async("x")) for _ in range(4)]
        while stub.methods().count("Page.printToPDF") < 4:
            await asyncio.sleep(0.02)
        await engine.aclose()
        return list(await asyncio.gather(*jobs, return_exceptions=True))

    assert codes(asyncio.run(run())) == {"closed"}
    gc.collect()
    assert noise == []


def test_aclose_does_not_wait_for_the_thread_pool(stub: DevToolsStub, noise: list[str]) -> None:
    stub.hang = {"Page.printToPDF"}
    engine = pdf.ChromePdfEngine.connect(stub.url)
    options = pdf.PdfOptions(print_timeout=8)

    async def run() -> tuple[float, list[Any]]:
        listen(noise)
        # One thread: the first print holds it and the others wait for it, as on a busy server.
        asyncio.get_running_loop().set_default_executor(
            concurrent.futures.ThreadPoolExecutor(max_workers=1)
        )
        jobs = [asyncio.ensure_future(engine.html_to_pdf_async("x", options)) for _ in range(3)]
        while "Page.printToPDF" not in stub.methods():
            await asyncio.sleep(0.02)
        started = time.monotonic()
        await engine.aclose()
        took = time.monotonic() - started
        return took, list(await asyncio.gather(*jobs, return_exceptions=True))

    took, results = asyncio.run(run())
    assert took < 3
    assert codes(results) == {"closed"}
    assert noise == []


def test_a_cancelled_aclose_still_closes(stub: DevToolsStub) -> None:
    engine = pdf.ChromePdfEngine.connect(stub.url)

    async def run() -> None:
        closing = asyncio.ensure_future(engine.aclose())
        await asyncio.sleep(0)
        closing.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await closing

    asyncio.run(run())
    wait_until(lambda: engine._browser is None)


# -- cancel ------------------------------------------------------------------


def test_cancelling_a_queued_job_returns_at_once_and_never_prints(
    stub: DevToolsStub, noise: list[str]
) -> None:
    engine = pdf.ChromePdfEngine.connect(stub.url)
    release = threading.Event()

    async def run() -> float:
        listen(noise)
        loop = asyncio.get_running_loop()
        loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=1))
        blocker = loop.run_in_executor(None, release.wait, 5)
        job = asyncio.ensure_future(engine.html_to_pdf_async("queued"))
        await asyncio.sleep(0.1)
        started = time.monotonic()
        job.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await job
        took = time.monotonic() - started
        release.set()
        await blocker
        return took

    assert asyncio.run(run()) < 1
    assert "Target.createTarget" not in stub.methods()
    assert noise == []
    engine.close()


def test_a_cancelled_print_logs_nothing_on_python_3_14(
    stub: DevToolsStub, noise: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    real_shield: Any = asyncio.shield

    def shield_3_14(arg: Any) -> Any:
        """CPython 3.14.0 to 3.14.2 report the error of a shielded future whose waiter left."""
        loop = asyncio.get_running_loop()
        inner = asyncio.ensure_future(arg)
        outer = real_shield(inner)

        def report(done: Any) -> None:
            if not done.cancelled() and done.exception() is not None:
                loop.call_exception_handler({"message": "exception in shielded future"})

        def waiter_finished(waiter: Any) -> None:
            if waiter.cancelled() and not inner.done():
                inner.add_done_callback(report)

        outer.add_done_callback(waiter_finished)
        return outer

    monkeypatch.setattr(asyncio, "shield", shield_3_14)
    stub.hang = {"Page.printToPDF"}
    engine = pdf.ChromePdfEngine.connect(stub.url)

    async def run() -> None:
        listen(noise)
        job = asyncio.ensure_future(engine.html_to_pdf_async("x"))
        while "Page.printToPDF" not in stub.methods():
            await asyncio.sleep(0.02)
        job.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await job

    asyncio.run(run())
    engine.close()
    assert noise == []


# -- crashes -----------------------------------------------------------------


def test_a_reset_during_the_handshake_is_a_pdf_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class Reset:
        """A socket whose peer went away right after it accepted (macOS says EINVAL)."""

        closed = False

        def getpeername(self) -> Any:
            raise OSError(22, "Invalid argument")

        def close(self) -> None:
            Reset.closed = True

    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: Reset())
    with pytest.raises(pdf.PdfError) as caught:
        pdf.ChromePdfEngine.connect("ws://127.0.0.1:9222/devtools/browser/x")
    assert caught.value.code == "browser_failed"
    assert Reset.closed


def test_an_os_error_while_starting_is_a_pdf_error(
    temp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def disk_full(self: Path, *args: Any, **kwargs: Any) -> Any:
        raise OSError(28, "No space left on device")

    engine = pdf.ChromePdfEngine(sys.executable)
    monkeypatch.setattr(Path, "open", disk_full)
    with pytest.raises(pdf.PdfError) as caught:
        engine.html_to_pdf("x")
    assert caught.value.code == "browser_failed"
    assert profiles(temp) == []


def start_fake_browser(stub: DevToolsStub, directory: Path) -> tuple[pdf.ChromePdfEngine, int]:
    """A "browser" that is a shell script with a helper process."""
    script, helper = directory / "fake chrome", directory / "helper.pid"
    script.write_text(
        "#!/bin/sh\n"
        "sleep 30 &\n"
        f'echo $! > "{helper}"\n'
        f"echo 'DevTools listening on {stub.url}' >&2\n"
        "wait\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    engine = pdf.ChromePdfEngine(script).launch()
    return engine, int(helper.read_text())


@posix_only
def test_a_crash_during_a_print_cleans_up_at_once(
    stub: DevToolsStub, temp: Path, noise: list[str]
) -> None:
    stub.hang = {"Page.printToPDF"}
    engine, helper = start_fake_browser(stub, temp)
    assert engine._browser is not None and engine._browser.pid is not None
    pid = engine._browser.pid

    def crash() -> None:
        wait_until(lambda: stub.methods().count("Page.printToPDF") == 3)
        os.kill(pid, KILL)
        for connection in list(stub._sockets):  # the stand-in's side of the dead browser
            connection.shutdown(socket.SHUT_RDWR)

    assert codes(print_in_threads(engine, "x", 3, crash)) == {"browser_failed"}
    # Before close() or another call: no process, no helper, no profile.
    assert profiles(temp) == []
    wait_until(lambda: not running(pid) and not running(helper))
    assert noise == []
    engine.close()


@posix_only
def test_an_interrupted_close_leaves_no_browser(
    stub: DevToolsStub, temp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, helper = start_fake_browser(stub, temp)
    browser = engine._browser
    assert browser is not None and browser.pid is not None
    pid = browser.pid

    def interrupted(*args: Any, **kwargs: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(browser.devtools, "send", interrupted)
    with pytest.raises(KeyboardInterrupt):
        engine.close()
    assert profiles(temp) == []
    wait_until(lambda: not running(pid) and not running(helper))


# -- a real browser ----------------------------------------------------------


@needs_browser
@pytest.mark.parametrize("how", ["sync", "async"])
def test_closing_a_real_browser_mid_print(how: str, temp: Path, noise: list[str]) -> None:
    engine = pdf.ChromePdfEngine().launch()
    assert engine._browser is not None and engine._browser.pid is not None
    pid = engine._browser.pid

    async def run() -> list[Any]:
        listen(noise)
        jobs = [asyncio.ensure_future(engine.html_to_pdf_async(BUSY)) for _ in range(3)]
        await asyncio.sleep(0.7)
        await engine.aclose()
        return list(await asyncio.gather(*jobs, return_exceptions=True))

    def close() -> None:
        time.sleep(0.7)
        engine.close()

    results = asyncio.run(run()) if how == "async" else print_in_threads(engine, BUSY, 3, close)
    assert codes(results) == {"closed"}
    assert profiles(temp) == []
    if sys.platform != "win32":
        wait_until(lambda: not running(pid))
    gc.collect()
    assert noise == []


@needs_browser
@posix_only
@pytest.mark.parametrize("how", ["sync", "async"])
def test_killing_a_real_browser_mid_print(how: str, temp: Path, noise: list[str]) -> None:
    engine = pdf.ChromePdfEngine().launch()
    assert engine._browser is not None and engine._browser.pid is not None
    pid = engine._browser.pid

    async def run() -> list[Any]:
        listen(noise)
        jobs = [asyncio.ensure_future(engine.html_to_pdf_async(BUSY)) for _ in range(3)]
        await asyncio.sleep(0.7)
        os.kill(pid, KILL)
        return list(await asyncio.gather(*jobs, return_exceptions=True))

    def kill() -> None:
        time.sleep(0.7)
        os.kill(pid, KILL)

    results = asyncio.run(run()) if how == "async" else print_in_threads(engine, BUSY, 3, kill)
    assert codes(results) == {"browser_failed"}
    assert profiles(temp) == []
    wait_until(lambda: not running(pid))
    assert engine.html_to_pdf("<p>again</p>").startswith(b"%PDF")  # a new browser takes over
    engine.close()
    assert profiles(temp) == []
    gc.collect()
    assert noise == []
