"""DevTools protocol commands over one WebSocket, from any number of threads."""

from __future__ import annotations

import contextlib
import json
import threading
import time
from typing import Any

from ._options import PdfError, check_cancelled
from ._websocket import WebSocket

#: How often a waiting thread looks at its cancel event and its deadline.
_POLL_SECONDS = 0.05


class _Call:
    def __init__(self, session: str | None) -> None:
        self.session = session
        self.done = threading.Event()
        self.reply: dict[str, Any] = {}
        self.error: str | None = None


class DevTools:
    """One reader thread hands each answer to the thread that sent the command."""

    def __init__(self, socket: WebSocket) -> None:
        self._socket = socket
        self._lock = threading.Lock()
        self._calls: dict[int, _Call] = {}
        self._last_id = 0
        self._ended: str | None = None
        self._reader = threading.Thread(
            target=self._read, name="lifeastroapi-devtools", daemon=True
        )
        self._reader.start()

    @property
    def alive(self) -> bool:
        return self._ended is None

    def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session: str | None = None,
        deadline: float,
        cancel: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Send one command and wait for its result until ``deadline`` (``time.monotonic``)."""
        check_cancelled(cancel)
        call = _Call(session)
        with self._lock:
            if self._ended is not None:
                raise PdfError(self._ended, code="browser_failed")
            self._last_id += 1
            call_id = self._last_id
            self._calls[call_id] = call
        message: dict[str, Any] = {"id": call_id, "method": method, "params": params or {}}
        if session is not None:
            message["sessionId"] = session
        try:
            self._socket.send(json.dumps(message, separators=(",", ":")))
            while not call.done.wait(_POLL_SECONDS):
                check_cancelled(cancel)
                if time.monotonic() > deadline:
                    raise PdfError(f"The browser did not answer {method} in time", code="timeout")
        finally:
            with self._lock:
                self._calls.pop(call_id, None)
        if call.error is not None:
            raise PdfError(call.error, code="browser_failed")
        error = call.reply.get("error")
        if isinstance(error, dict):
            detail = error.get("message", "unknown error")
            raise PdfError(f"DevTools {method}: {detail}", code="browser_failed")
        result = call.reply.get("result")
        return result if isinstance(result, dict) else {}

    def end(self, reason: str) -> None:
        """Fail every waiting call and close the connection."""
        self._fail(reason)
        self._socket.close()

    def forget(self) -> None:
        self._ended = "The browser belongs to the parent process"
        self._socket.forget()

    def _fail(self, reason: str) -> None:
        with self._lock:
            if self._ended is None:
                self._ended = reason
            calls = list(self._calls.values())
            self._calls.clear()
        for call in calls:
            call.error = self._ended
            call.done.set()

    def _read(self) -> None:
        reason = "The connection to the browser ended"
        try:
            while True:
                message = json.loads(self._socket.receive().decode("utf-8", "surrogatepass"))
                if not isinstance(message, dict):
                    continue
                if "id" in message:
                    with self._lock:
                        call = self._calls.get(message["id"])
                    if call is not None:
                        call.reply = message
                        call.done.set()
                else:
                    self._on_event(message)
        except PdfError as error:
            reason = error.message
        except Exception as error:
            reason = f"{reason}: {error}"
        self._fail(reason)
        with contextlib.suppress(OSError):
            self._socket.close()

    def _on_event(self, event: dict[str, Any]) -> None:
        # A tab that crashed or went away never answers, so fail what waits on it.
        method = event.get("method")
        if method == "Target.detachedFromTarget":
            session = (event.get("params") or {}).get("sessionId")
        elif method == "Inspector.targetCrashed":
            session = event.get("sessionId")
        else:
            return
        if not session:
            return
        with self._lock:
            calls = [call for call in self._calls.values() if call.session == session]
        for call in calls:
            call.error = "The browser tab closed or crashed while printing"
            call.done.set()
