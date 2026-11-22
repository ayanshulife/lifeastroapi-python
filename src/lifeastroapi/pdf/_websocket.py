"""A small WebSocket client (RFC 6455) for the Chrome DevTools protocol.

Plain ``ws://`` only: DevTools listens on the local machine. One thread reads and
any number of threads send.
"""

from __future__ import annotations

import base64
import contextlib
import os
import socket
import struct
import threading
from urllib.parse import urlsplit

from ._options import PdfError

_TEXT = 0x1
_CLOSE = 0x8
_PING = 0x9
_PONG = 0xA
_MAX_MESSAGE = 1 << 30
_MAX_HANDSHAKE = 16384
#: Also the limit for one blocked send. A read that times out simply waits again.
_SOCKET_TIMEOUT = 30.0


def _failed(message: str) -> PdfError:
    return PdfError(message, code="browser_failed")


class WebSocket:
    def __init__(self, url: str, timeout: float = 10.0) -> None:
        parts = urlsplit(url)
        if parts.scheme != "ws" or not parts.hostname:
            raise ValueError(f"not a ws:// URL: {url}")
        port = parts.port or 80
        self._closed = False
        self._send_lock = threading.Lock()
        self._buffer = bytearray()
        try:
            self._sock = socket.create_connection((parts.hostname, port), timeout=timeout)
        except OSError as error:
            raise _failed(f"Cannot connect to the browser at {url}: {error}") from error
        try:
            self._handshake(parts.path or "/", parts.query)
            self._sock.settimeout(_SOCKET_TIMEOUT)
            with contextlib.suppress(OSError):
                self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError as error:  # also from getpeername, when the browser died as it accepted
            self._sock.close()
            raise _failed(f"The DevTools handshake failed: {error}") from error
        except BaseException:
            self._sock.close()
            raise

    def _handshake(self, path: str, query: str) -> None:
        if query:
            path += "?" + query
        # Chrome accepts only an IP address or localhost in Host, so a container name will not do.
        address = self._sock.getpeername()
        host = f"[{address[0]}]" if ":" in address[0] else address[0]
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\nHost: {host}:{address[1]}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self._sock.sendall(request.encode("utf-8"))
        while b"\r\n\r\n" not in self._buffer:
            chunk = self._sock.recv(4096)
            if not chunk or len(self._buffer) > _MAX_HANDSHAKE:
                raise _failed("The browser closed the DevTools handshake")
            self._buffer += chunk
        head, _, rest = self._buffer.partition(b"\r\n\r\n")
        status = bytes(head).split(b"\r\n", 1)[0]
        if not status.startswith(b"HTTP/1.") or status[9:12] != b"101":
            text = status.decode("latin-1")
            raise _failed(f"The browser refused the DevTools connection: {text}")
        self._buffer = bytearray(rest)

    def send(self, text: str) -> None:
        self._send_frame(_TEXT, text.encode("utf-8"))

    def receive(self) -> bytes:
        """The next text message. Answers pings; raises when the connection ends."""
        message = bytearray()
        while True:
            first, second = self._read(2)
            size = second & 0x7F
            if size == 126:
                (size,) = struct.unpack("!H", self._read(2))
            elif size == 127:
                (size,) = struct.unpack("!Q", self._read(8))
            if size + len(message) > _MAX_MESSAGE:
                raise _failed("The browser sent a DevTools message that is too large")
            mask = self._read(4) if second & 0x80 else b""
            payload = self._read(size) if size else b""
            if mask:
                payload = apply_mask(payload, mask)
            opcode = first & 0x0F
            if opcode == _CLOSE:
                raise _failed("The browser closed the DevTools connection")
            if opcode == _PING:
                self._send_frame(_PONG, payload)
            elif opcode != _PONG:
                message += payload
                if first & 0x80:
                    return bytes(message)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._send_lock.acquire(timeout=1.0):
            try:
                with contextlib.suppress(OSError):
                    self._sock.sendall(frame(_CLOSE, b"\x03\xe8"))
            finally:
                self._send_lock.release()
        with contextlib.suppress(OSError):
            self._sock.shutdown(socket.SHUT_RDWR)  # wakes the thread that is reading
        self._sock.close()

    def forget(self) -> None:
        """Drop this process's copy of the socket after a fork; the parent still uses it."""
        self._closed = True
        with contextlib.suppress(OSError):
            self._sock.close()

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        data = frame(opcode, payload)
        with self._send_lock:
            try:
                self._sock.sendall(data)
            except OSError as error:
                # Part of a frame may have gone out, so the connection cannot be used again.
                with contextlib.suppress(OSError):
                    self._sock.shutdown(socket.SHUT_RDWR)
                raise _failed(f"The connection to the browser was lost: {error}") from error

    def _read(self, size: int) -> bytes:
        while len(self._buffer) < size:
            try:
                chunk = self._sock.recv(max(65536, min(size - len(self._buffer), 1 << 20)))
            except socket.timeout:
                if self._closed:
                    raise _failed("The DevTools connection was closed") from None
                continue
            except OSError as error:
                raise _failed(f"The connection to the browser was lost: {error}") from error
            if not chunk:
                raise _failed("The browser closed the DevTools connection")
            self._buffer += chunk
        out = bytes(self._buffer[:size])
        del self._buffer[:size]
        return out


def apply_mask(payload: bytes, mask: bytes) -> bytes:
    size = len(payload)
    if not size:
        return payload
    key = (mask * (size // 4 + 1))[:size]
    masked = int.from_bytes(payload, "big") ^ int.from_bytes(key, "big")
    return masked.to_bytes(size, "big")


def frame(opcode: int, payload: bytes) -> bytes:
    """One final, masked client frame."""
    size = len(payload)
    if size < 126:
        head = struct.pack("!BB", 0x80 | opcode, 0x80 | size)
    elif size < 65536:
        head = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, size)
    else:
        head = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, size)
    mask = os.urandom(4)
    return head + mask + apply_mask(payload, mask)
