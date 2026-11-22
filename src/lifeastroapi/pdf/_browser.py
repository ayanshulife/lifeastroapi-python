"""Finding, starting and stopping a headless browser process."""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from ._devtools import DevTools
from ._options import PdfError, check_cancelled
from ._websocket import WebSocket

#: Environment variables that name the browser, in the order they are tried.
BROWSER_ENV = ("LIFEASTRO_CHROME", "CHROME_PATH", "PUPPETEER_EXECUTABLE_PATH")

NOT_FOUND = (
    "No Chrome, Chromium or Microsoft Edge was found, and one is needed to make a PDF.\n"
    "  Debian / Ubuntu / Docker: apt-get install chromium fonts-noto-core\n"
    "  macOS:                    install Google Chrome, or: brew install --cask google-chrome\n"
    "  Windows:                  install Google Chrome, or use the Microsoft Edge that is there\n"
    "If it is installed somewhere else, pass ChromePdfEngine(executable=...) or set "
    "LIFEASTRO_CHROME to its path. Without a browser, use GotenbergPdfEngine. "
    "The render_*_html functions need no browser."
)

_FLAGS = (
    "--headless=new",
    "--remote-debugging-port=0",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-sync",
    "--disable-dev-shm-usage",  # /dev/shm is tiny in Docker
    "--hide-scrollbars",
    "--mute-audio",
    "--password-store=basic",  # no keyring or keychain prompt on a desktop
    "--use-mock-keychain",
)
_PORT_FILE = re.compile(rb"(\d{1,5})\r?\n(/devtools/browser/[0-9A-Fa-f-]{36})")
_LISTENING = re.compile(rb"DevTools listening on (ws://\S+)\s")
_LINUX_NAMES = (
    "google-chrome-stable",
    "google-chrome",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
    "microsoft-edge-stable",
)


def _candidates() -> Iterator[str]:
    if sys.platform == "darwin":
        for root in ("/Applications", os.path.expanduser("~/Applications")):
            for app in ("Google Chrome", "Chromium", "Microsoft Edge"):
                yield f"{root}/{app}.app/Contents/MacOS/{app}"
    elif sys.platform == "win32":
        variables = ("PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "LOCALAPPDATA")
        roots = [root for root in map(os.environ.get, variables) if root]
        for parts in (
            ("Google", "Chrome", "Application", "chrome.exe"),
            ("Chromium", "Application", "chrome.exe"),
            ("Microsoft", "Edge", "Application", "msedge.exe"),
        ):
            for root in roots:
                yield os.path.join(root, *parts)
    else:
        yield from _LINUX_NAMES
        yield "/usr/bin/chromium"
        yield "/snap/bin/chromium"


def find_browser() -> str | None:
    """The Chrome, Chromium or Edge executable to use, or ``None``.

    Looks at ``LIFEASTRO_CHROME``, ``CHROME_PATH`` and ``PUPPETEER_EXECUTABLE_PATH``,
    then at the usual install locations of the operating system.
    """
    named = [value for value in map(os.environ.get, BROWSER_ENV) if value]
    for candidate in (*named, *_candidates()):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def default_no_sandbox() -> bool:
    """``--no-sandbox`` is used on its own only as root, where Chrome cannot start without it."""
    return sys.platform != "win32" and os.geteuid() == 0


class Browser:
    """A connection to a browser and, when this process started it, the process and its profile."""

    def __init__(
        self,
        devtools: DevTools,
        process: subprocess.Popen[bytes] | None = None,
        directory: str | None = None,
    ) -> None:
        self.devtools = devtools
        self._process = process
        self._directory = directory
        self._owner = os.getpid()
        self._stop_lock = threading.Lock()
        self._stopped = False

    @property
    def alive(self) -> bool:
        return self.devtools.alive and not self._stopped

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    @property
    def directory(self) -> str | None:
        return self._directory

    @classmethod
    def connect(cls, url: str, timeout: float) -> Browser:
        return cls(DevTools(WebSocket(url, timeout)))

    @classmethod
    def launch(
        cls,
        executable: str,
        *,
        no_sandbox: bool,
        args: Sequence[str],
        timeout: float,
        cancel: threading.Event | None,
        closed: threading.Event,
    ) -> Browser:
        check_cancelled(cancel)
        try:
            directory = tempfile.mkdtemp(prefix="lifeastro-chrome-")
        except OSError as error:
            raise PdfError(
                f"Cannot create a temporary browser profile: {error}", code="browser_failed"
            ) from error
        process: subprocess.Popen[bytes] | None = None
        try:
            profile = os.path.join(directory, "profile")
            log = Path(directory, "browser.log")
            command = [executable, *_FLAGS, f"--user-data-dir={profile}"]
            if no_sandbox:
                command.append("--no-sandbox")
            command += [*args, "about:blank"]
            # Output goes to a file: nothing here would drain a pipe while the browser runs.
            with log.open("wb") as output:
                try:
                    process = _spawn(command, output)
                except OSError as error:
                    raise PdfError(
                        f"Cannot start the browser {executable!r}: {error}. "
                        "Check the executable path, or set LIFEASTRO_CHROME.",
                        code="browser_not_found",
                    ) from error
            deadline = time.monotonic() + timeout
            url = _await_endpoint(process, Path(profile), log, deadline, cancel, closed)
            devtools = DevTools(WebSocket(url, max(1.0, deadline - time.monotonic())))
            return cls(devtools, process, directory)
        except BaseException as error:
            if process is not None:
                _kill(process)
            remove_tree(directory)
            if isinstance(error, OSError):  # a full disk, no free file descriptors
                raise PdfError(
                    f"Cannot start the browser: {error}", code="browser_failed"
                ) from error
            raise

    def stop(self) -> None:
        """Close the connection and, for a browser started here, the browser and its profile.

        One that crashed, does not answer, or whose closing is interrupted is killed with its
        helper processes.
        """
        if self._owner != os.getpid():
            return  # a forked child must not touch its parent's browser
        with self._stop_lock:
            if self._stopped:
                return
            self._stopped = True
            process = self._process
            try:
                if process is not None and self.devtools.alive:
                    with contextlib.suppress(PdfError):
                        self.devtools.send("Browser.close", deadline=time.monotonic() + 3)
                    self.devtools.end("The PDF engine was closed")
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        process.wait(timeout=5)
            finally:
                self.devtools.end("The PDF engine was closed")
                if process is not None and process.returncode is None:
                    _kill(process)
                if self._directory is not None:
                    remove_tree(self._directory)

    def forget(self) -> None:
        """In a forked child: let go of the parent's browser without touching it."""
        self._stopped = True
        self.devtools.forget()
        if self._process is not None:
            self._process.returncode = 0  # not this process's child, so nothing to wait for


def _spawn(command: list[str], output: Any) -> subprocess.Popen[bytes]:
    if sys.platform == "win32":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
    # Its own process group, so that its helper processes can be stopped with it.
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=output,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _await_endpoint(
    process: subprocess.Popen[bytes],
    profile: Path,
    log: Path,
    deadline: float,
    cancel: threading.Event | None,
    closed: threading.Event,
) -> str:
    while True:
        check_cancelled(cancel)
        if closed.is_set():
            raise PdfError("The PDF engine was closed", code="closed")
        exited = process.poll()
        port_file = _PORT_FILE.match(_read(profile / "DevToolsActivePort"))
        if port_file is not None:
            port, path = (part.decode("ascii") for part in port_file.groups())
            return f"ws://127.0.0.1:{port}{path}"
        output = _read(log)
        # A confined browser (snap) has its own /tmp, so also look at what it printed.
        listening = _LISTENING.search(output)
        if listening is not None:
            return listening.group(1).decode("utf-8", "replace")
        # On Windows the launcher may hand over to another process and exit with 0.
        if exited is not None and (exited != 0 or sys.platform != "win32"):
            raise _start_error(f"The browser exited with status {exited}", output, "browser_failed")
        if time.monotonic() > deadline:
            raise _start_error("The browser did not start in time", output, "timeout")
        time.sleep(0.05)


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:  # not written yet, or still locked by the browser
        return b""


def _start_error(reason: str, output: bytes, code: str) -> PdfError:
    text = output.decode("utf-8", "replace").strip()[-2000:]
    if "sandbox" in text.lower():
        reason += (
            " (its sandbox is not available here: run as a user that can use it, or pass "
            "ChromePdfEngine(no_sandbox=True) if you print only HTML you trust)"
        )
    return PdfError(f"{reason}: {text}" if text else reason, code=code)


def _kill(process: subprocess.Popen[bytes]) -> None:
    """Stop the process started here and its helpers, always by pid and never by name."""
    # No poll() first: until the process is reaped its pid and group are still the browser's,
    # also when it has crashed and only its helpers are left.
    if process.returncode is None:
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=10,
                    check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                os.killpg(process.pid, signal.SIGKILL)
        with contextlib.suppress(OSError):
            process.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=5)


def remove_tree(directory: str) -> None:
    # Windows keeps files locked for a moment after the browser exits.
    for _ in range(25):
        shutil.rmtree(directory, ignore_errors=True)
        if not os.path.exists(directory):
            return
        time.sleep(0.2)
