"""The Chrome / Chromium / Edge engine."""

from __future__ import annotations

import base64
import contextlib
import os
import threading
import time
import weakref
from collections.abc import Sequence
from types import TracebackType
from typing import Any

from ._browser import NOT_FOUND, Browser, default_no_sandbox, find_browser
from ._devtools import DevTools
from ._options import PdfError, PdfMargin, PdfOptions, check_cancelled, printable
from ._print_css import with_print_css
from ._threads import run_in_thread, run_to_completion

_WAIT_FOR_LOAD = """(async () => {
  if (document.readyState !== 'complete') {
    await new Promise((r) => window.addEventListener('load', r, { once: true }));
  }
  await Promise.all(Array.from(document.images).map((img) => img.complete ? null :
    new Promise((r) => { img.addEventListener('load', r, { once: true });
                         img.addEventListener('error', r, { once: true }); })));
  if (document.fonts && document.fonts.ready) await document.fonts.ready;
  return true;
})()"""
_CHUNK = 1 << 20


class ChromePdfEngine:
    """Prints with a headless Chrome, Chromium or Microsoft Edge on your own machine.

    The browser starts on first use and is reused, which makes the next PDFs fast. One
    engine can be shared between threads and ``asyncio`` tasks. It also survives ``fork``
    (Celery, gunicorn): each child process starts its own browser. Close it when done::

        with ChromePdfEngine() as engine:
            for report in reports:
                pdf = kundli_lite_pdf(report, engine=engine)

    ``async with`` and ``await engine.aclose()`` do the same in ``asyncio`` code. An engine
    left open is closed when the process exits normally. That excludes SIGTERM, unless a
    handler turns it into ``sys.exit()``, and ``os._exit`` (Celery's pool workers): call
    :meth:`close` before those.

    :param executable: The browser to run. Default: :func:`find_browser`.
    :param no_sandbox: Pass ``--no-sandbox``. Default: only when running as root, where
        Chrome cannot start otherwise (the usual case in Docker).
    :param args: Extra command-line switches for the browser.
    :param launch_timeout: Seconds allowed for the browser to start.
    """

    def __init__(
        self,
        executable: str | os.PathLike[str] | None = None,
        *,
        no_sandbox: bool | None = None,
        args: Sequence[str] = (),
        launch_timeout: float = 30.0,
    ) -> None:
        self._executable = os.fspath(executable) if executable is not None else None
        self._no_sandbox = no_sandbox
        self._args = tuple(args)
        self._launch_timeout = launch_timeout
        self._url: str | None = None
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._browser: Browser | None = None
        self._finalizer: weakref.finalize[[], ChromePdfEngine] | None = None
        self._child_exit: Any = None
        _ENGINES.add(self)

    @classmethod
    def connect(cls, web_socket_url: str, *, timeout: float = 10.0) -> ChromePdfEngine:
        """Use a browser that already runs with remote debugging, for example a container.

        ``web_socket_url`` is the ``webSocketDebuggerUrl`` from
        ``http://host:9222/json/version``. ``close()`` disconnects and leaves it running.
        """
        engine = cls(launch_timeout=timeout)
        engine._url = web_socket_url
        return engine.launch()

    def launch(self) -> ChromePdfEngine:
        """Start the browser now instead of on first use. Returns the engine."""
        self._ready(None)
        return self

    def html_to_pdf(
        self,
        html: str,
        options: PdfOptions | None = None,
        *,
        cancel: threading.Event | None = None,
    ) -> bytes:
        """Print a complete HTML document to PDF bytes.

        :param cancel: Set this event from another thread to stop the job.
        :raises PdfError: No browser, a browser failure, a timeout or a cancellation.
        """
        options = options or PdfOptions()
        html = printable(with_print_css(html, options))
        browser = self._ready(cancel)
        try:
            return _print(browser.devtools, html, options, cancel)
        except PdfError as error:
            closed = self._closed.is_set()
            if not browser.devtools.alive:
                browser.stop()  # crashed or closed: gone, profile included, before the call returns
            if closed and error.code != "cancelled":
                raise PdfError("The PDF engine was closed", code="closed") from error
            raise

    async def html_to_pdf_async(self, html: str, options: PdfOptions | None = None) -> bytes:
        """:meth:`html_to_pdf` without blocking the event loop. Cancelling the task stops it."""
        return await run_in_thread(lambda stop: self.html_to_pdf(html, options, cancel=stop))

    def close(self) -> None:
        """Stop the browser and delete its profile. Safe to call twice."""
        self._closed.set()
        with self._lock:
            self._retire()

    async def aclose(self) -> None:
        """:meth:`close` for ``asyncio`` code: prints still running fail with ``closed``."""
        self._closed.set()  # now, so that no waiting job starts
        await run_to_completion(self.close)

    def __enter__(self) -> ChromePdfEngine:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    async def __aenter__(self) -> ChromePdfEngine:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    def _ready(self, cancel: threading.Event | None) -> Browser:
        while not self._lock.acquire(timeout=0.05):
            check_cancelled(cancel)
        try:
            if self._closed.is_set():
                raise PdfError("The PDF engine was closed", code="closed")
            if self._browser is not None and self._browser.alive:
                return self._browser
            self._retire()  # the previous browser died
            browser = self._start(cancel)
            self._browser = browser
            # Runs if the engine is garbage collected, and when the interpreter exits.
            self._finalizer = weakref.finalize(self, browser.stop)
            # multiprocessing children leave with os._exit, which skips atexit but runs these.
            from multiprocessing import util

            self._child_exit = util.Finalize(self, browser.stop, exitpriority=10)
            return browser
        finally:
            self._lock.release()

    def _start(self, cancel: threading.Event | None) -> Browser:
        if self._url is not None:
            return Browser.connect(self._url, self._launch_timeout)
        check_cancelled(cancel)
        executable = self._executable or find_browser()
        if executable is None:
            raise PdfError(NOT_FOUND, code="browser_not_found")
        no_sandbox = self._no_sandbox if self._no_sandbox is not None else default_no_sandbox()
        return Browser.launch(
            executable,
            no_sandbox=no_sandbox,
            args=self._args,
            timeout=self._launch_timeout,
            cancel=cancel,
            closed=self._closed,
        )

    def _retire(self) -> None:
        if self._child_exit is not None:
            self._child_exit.cancel()
            self._child_exit = None
        if self._finalizer is not None:
            self._finalizer()
            self._finalizer = None
        self._browser = None

    def _after_fork(self) -> None:
        self._lock = threading.Lock()  # may have been held by a thread that is not in the child
        closed = self._closed.is_set()
        self._closed = threading.Event()
        if closed:
            self._closed.set()
        self._child_exit = None  # the parent's; stop() does nothing in another process anyway
        if self._finalizer is not None:
            self._finalizer.detach()
            self._finalizer = None
        if self._browser is not None:
            self._browser.forget()
            self._browser = None


_ENGINES: weakref.WeakSet[ChromePdfEngine] = weakref.WeakSet()


def _after_fork_in_child() -> None:
    for engine in list(_ENGINES):
        engine._after_fork()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork_in_child)


def _print_params(options: PdfOptions) -> dict[str, Any]:
    width, height = options.paper_inches()
    top, bottom, left, right = (options.margin or PdfMargin()).inches()
    params: dict[str, Any] = {
        # The orientation is already in the paper width and height.
        "landscape": False,
        "printBackground": options.print_background,
        "preferCSSPageSize": options.uses_css_page_size(),
        "paperWidth": width,
        "paperHeight": height,
        "marginTop": top,
        "marginBottom": bottom,
        "marginLeft": left,
        "marginRight": right,
        "scale": options.scale if options.scale is not None else 1.0,
        "displayHeaderFooter": bool(options.display_header_footer),
        "transferMode": "ReturnAsStream",
    }
    if options.display_header_footer:
        params["headerTemplate"] = printable(options.header_template or "<span></span>")
        params["footerTemplate"] = printable(options.footer_template or "<span></span>")
    return params


def _print(
    devtools: DevTools, html: str, options: PdfOptions, cancel: threading.Event | None
) -> bytes:
    check_cancelled(cancel)
    deadline = time.monotonic() + options.timeout
    try:
        # Not cancellable: once the command is out, the tab's id is needed to close it again.
        target = devtools.send(
            "Target.createTarget", {"url": "about:blank"}, deadline=deadline
        ).get("targetId")
    except PdfError as error:
        if error.code == "timeout":
            devtools.end("The browser stopped answering")  # the next call starts a new one
        raise
    if not isinstance(target, str):
        raise PdfError("The browser did not open a tab", code="browser_failed")
    try:
        try:
            session = _load(devtools, target, html, deadline, cancel)
        except PdfError as error:
            if error.code != "timeout":
                raise
            raise PdfError(
                f"The page did not finish loading in {options.timeout:g} s. Check that the "
                "logo, image and font URLs answer, or raise PdfOptions(timeout=...)",
                code="timeout",
            ) from error
        return _print_tab(devtools, session, options, cancel)
    finally:
        if devtools.alive:
            with contextlib.suppress(PdfError):
                devtools.send(
                    "Target.closeTarget", {"targetId": target}, deadline=time.monotonic() + 5
                )


def _load(
    devtools: DevTools,
    target: str,
    html: str,
    deadline: float,
    cancel: threading.Event | None,
) -> str:
    session = devtools.send(
        "Target.attachToTarget",
        {"targetId": target, "flatten": True},
        deadline=deadline,
        cancel=cancel,
    ).get("sessionId")
    if not isinstance(session, str):
        raise PdfError("Could not attach to the browser tab", code="browser_failed")

    def send(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return devtools.send(method, params, session=session, deadline=deadline, cancel=cancel)

    send("Inspector.enable")
    send("Page.enable")
    frame = (send("Page.getFrameTree").get("frameTree") or {}).get("frame") or {}
    if not isinstance(frame.get("id"), str):
        raise PdfError("Could not read the tab's frame", code="browser_failed")
    send("Page.setDocumentContent", {"frameId": frame["id"], "html": html})
    send(
        "Runtime.evaluate",
        {"expression": _WAIT_FOR_LOAD, "awaitPromise": True, "returnByValue": True},
    )
    return session


def _print_tab(
    devtools: DevTools, session: str, options: PdfOptions, cancel: threading.Event | None
) -> bytes:
    deadline = time.monotonic() + options.print_timeout

    def send(method: str, params: dict[str, Any]) -> dict[str, Any]:
        return devtools.send(method, params, session=session, deadline=deadline, cancel=cancel)

    printed = send("Page.printToPDF", _print_params(options))
    stream = printed.get("stream")
    out = bytearray()
    try:
        if stream:
            while True:
                part = send("IO.read", {"handle": stream, "size": _CHUNK})
                data = str(part.get("data") or "")
                out += (
                    base64.b64decode(data) if part.get("base64Encoded") else data.encode("latin-1")
                )
                if part.get("eof"):
                    break
            send("IO.close", {"handle": stream})
        else:  # a browser too old for streams sends the bytes in the answer
            out += base64.b64decode(str(printed.get("data") or ""))
    except ValueError as error:
        raise PdfError("The browser returned unreadable PDF data", code="browser_failed") from error
    if not out.startswith(b"%PDF"):
        raise PdfError("The browser returned no PDF data", code="browser_failed")
    return bytes(out)
