"""A stand-in for a browser's DevTools WebSocket, for the engine tests."""

from __future__ import annotations

import base64
import contextlib
import json
import socket
import struct
import threading
import time
from typing import Any

from lifeastroapi.pdf._websocket import apply_mask


class DevToolsStub:
    """Prints ``%PDF`` followed by the HTML of the tab, so a test can see who got which PDF."""

    def __init__(self) -> None:
        self.server = socket.create_server(("127.0.0.1", 0))
        self.url = f"ws://127.0.0.1:{self.server.getsockname()[1]}/devtools/browser/stub?a=1"
        self.hang: set[str] = set()
        self.drop: set[str] = set()
        self.crash: set[str] = set()
        self.errors: dict[str, str] = {}
        self.delay = 0.0
        self.fragment = False
        self.ping = False
        self.pongs = 0
        self.connections = 0
        self.handshake = b""
        self.calls: list[tuple[str, dict[str, Any], str | None]] = []
        self._html: dict[str, str] = {}
        self._sockets: list[socket.socket] = []
        self._count = 0
        self._lock = threading.Lock()
        threading.Thread(target=self._accept, daemon=True).start()

    def methods(self) -> list[str]:
        return [method for method, _params, _session in self.calls]

    def params(self, method: str) -> dict[str, Any]:
        return next(params for name, params, _session in self.calls if name == method)

    def wait_for(self, method: str) -> None:
        deadline = time.monotonic() + 5
        while method not in self.methods():
            assert time.monotonic() < deadline, f"{method} never came"
            time.sleep(0.01)

    def close(self) -> None:
        for sock in [self.server, *self._sockets]:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
            sock.close()

    def _accept(self) -> None:
        with contextlib.suppress(OSError):
            while True:
                sock, _address = self.server.accept()
                self.connections += 1
                self._sockets.append(sock)
                threading.Thread(target=self._serve, args=(sock,), daemon=True).start()

    def _serve(self, sock: socket.socket) -> None:
        send_lock = threading.Lock()
        with contextlib.suppress(OSError, EOFError):
            head = b""
            while not head.endswith(b"\r\n\r\n"):
                head += _exactly(sock, 1)
            self.handshake = head
            sock.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n\r\n")
            while True:
                first, second = _exactly(sock, 2)
                size = second & 0x7F
                if size == 126:
                    (size,) = struct.unpack("!H", _exactly(sock, 2))
                elif size == 127:
                    (size,) = struct.unpack("!Q", _exactly(sock, 8))
                assert second & 0x80, "client frames are masked"
                mask = _exactly(sock, 4)
                payload = apply_mask(_exactly(sock, size), mask)
                if first & 0x0F == 0x8:
                    return
                if first & 0x0F == 0xA:
                    self.pongs += 1
                    continue
                message = json.loads(payload)
                threading.Thread(
                    target=self._answer, args=(sock, send_lock, message), daemon=True
                ).start()

    def _answer(self, sock: socket.socket, lock: threading.Lock, message: dict[str, Any]) -> None:
        method, params = message["method"], message["params"]
        session = message.get("sessionId")
        result: dict[str, Any] = {}
        with self._lock:
            self.calls.append((method, params, session))
            if method == "Target.createTarget":
                self._count += 1
                result = {"targetId": f"target{self._count}"}
        if method in self.drop:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
            return
        if method in self.crash:
            event: dict[str, Any] = {
                "method": "Inspector.targetCrashed",
                "params": {},
                "sessionId": session,
            }
            self._send(sock, lock, event)
            return
        if method in self.hang:
            return
        if self.delay:
            time.sleep(self.delay * (hash((message["id"], method)) % 5 + 1) / 5)
        if method == "Target.attachToTarget":
            result = {"sessionId": "session-" + params["targetId"]}
        elif method == "Page.getFrameTree":
            result = {"frameTree": {"frame": {"id": f"frame-{session}"}}}
        elif method == "Page.setDocumentContent":
            self._html[str(session)] = params["html"]
        elif method == "Page.printToPDF":
            result = {"stream": f"stream-{session}"}
        elif method == "IO.read":
            data = b"%PDF" + self._html[str(session)].encode()
            result = {"data": base64.b64encode(data).decode(), "base64Encoded": True, "eof": True}
        reply: dict[str, Any] = {"id": message["id"], "result": result}
        if method in self.errors:
            reply = {"id": message["id"], "error": {"message": self.errors[method]}}
        self._send(sock, lock, reply)

    def _send(self, sock: socket.socket, lock: threading.Lock, message: dict[str, Any]) -> None:
        data = json.dumps(message).encode()
        with lock, contextlib.suppress(OSError):
            if self.ping:
                sock.sendall(_frame(0x89, b"hi"))
            if self.fragment and len(data) > 2:
                middle = len(data) // 2
                sock.sendall(_frame(0x01, data[:middle]) + _frame(0x80, data[middle:]))
            else:
                sock.sendall(_frame(0x81, data))


def _exactly(sock: socket.socket, size: int) -> bytes:
    out = b""
    while len(out) < size:
        chunk = sock.recv(size - len(out))
        if not chunk:
            raise EOFError
        out += chunk
    return out


def _frame(first: int, payload: bytes) -> bytes:
    size = len(payload)
    if size < 126:
        return struct.pack("!BB", first, size) + payload
    if size < 65536:
        return struct.pack("!BBH", first, 126, size) + payload
    return struct.pack("!BBQ", first, 127, size) + payload
