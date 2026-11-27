"""Errors raised by the SDK.

Every non-2xx response raises a :class:`LifeAstroError` subclass carrying the
API's ``code``, the HTTP ``status`` and the ``request_id`` (quote it to
support). Network failures raise :class:`LifeAstroConnectionError`, and
timeouts its subclass :class:`LifeAstroTimeoutError`.
"""

from __future__ import annotations

from typing import Any


class LifeAstroError(Exception):
    """Base class of every error raised by the SDK."""

    message: str
    """Human-readable message from the API (or the SDK)."""
    code: str
    """Machine-readable code, e.g. ``insufficient_credits`` or ``timeout``."""
    status: int
    """HTTP status code; ``0`` when no response was received."""
    request_id: str | None
    """The API's request id, when present. Quote it to support."""
    body: Any
    """The parsed response body, when there was one."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status: int,
        request_id: str | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.request_id = request_id
        self.body = body

    def __str__(self) -> str:
        details = [f"code={self.code}"]
        if self.status:
            details.insert(0, f"HTTP {self.status}")
        if self.request_id:
            details.append(f"request_id={self.request_id}")
        return f"{self.message} ({', '.join(details)})"


class BadRequestError(LifeAstroError):
    """400: a query parameter was missing, malformed or out of range."""


class AuthenticationError(LifeAstroError):
    """401: missing or invalid API key."""


class PaymentRequiredError(LifeAstroError):
    """402: out of credits, trial used up, or payment required."""


class PermissionDeniedError(LifeAstroError):
    """403: the key is valid but not allowed (plan, IP allow-list, suspended account)."""


class NotFoundError(LifeAstroError):
    """404: unknown path or sub-resource (for example an unknown yoga id)."""


class RateLimitError(LifeAstroError):
    """429: rate limit or daily quota reached."""

    retry_after: float | None
    """Seconds to wait before retrying, from the ``Retry-After`` header."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status: int,
        request_id: str | None = None,
        body: Any = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, code=code, status=status, request_id=request_id, body=body)
        self.retry_after = retry_after


class ServerError(LifeAstroError):
    """5xx: the API failed to answer."""


class LifeAstroConnectionError(LifeAstroError):
    """The request did not get a response: DNS, connection or network failure."""

    def __init__(self, message: str, *, code: str = "connection_error") -> None:
        super().__init__(message, code=code, status=0)


class LifeAstroTimeoutError(LifeAstroConnectionError):
    """The request timed out (``code == "timeout"``)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="timeout")


def _status_code_name(status: int) -> str:
    if status >= 500:
        return "internal_error"
    if status >= 400:
        return "bad_request"
    return "error"


def error_from_response(status: int, body: Any, retry_after: float | None = None) -> LifeAstroError:
    """Build the error subclass for an HTTP status and parsed body.

    The API's error body is ``{"error": {"code", "message", "request_id"}}``.
    """
    parsed = body.get("error") if isinstance(body, dict) else None
    if not isinstance(parsed, dict):
        parsed = {}
    code = parsed.get("code")
    message = parsed.get("message")
    request_id = parsed.get("request_id")
    kwargs: dict[str, Any] = {
        "code": code if isinstance(code, str) and code else _status_code_name(status),
        "status": status,
        "request_id": request_id if isinstance(request_id, str) else None,
        "body": body,
    }
    text = message if isinstance(message, str) and message else f"HTTP {status}"
    return _build(status, text, retry_after, kwargs)


def non_json_error(status: int, text: str, retry_after: float | None = None) -> LifeAstroError:
    """The error for a response whose body is not JSON: it did not come from the API
    (an HTML page from a proxy, firewall or CDN in between). Same class per status as
    :func:`error_from_response`, with code ``non_json_response``."""
    snippet = " ".join(text.split())[:120]
    message = (
        f"The response did not come from the API as JSON (HTTP {status}). "
        f"A proxy, firewall or CDN in between may have answered. Body starts: {snippet}"
    )
    kwargs: dict[str, Any] = {"code": "non_json_response", "status": status, "body": text}
    return _build(status, message, retry_after, kwargs)


def _build(
    status: int, text: str, retry_after: float | None, kwargs: dict[str, Any]
) -> LifeAstroError:
    if status == 400:
        return BadRequestError(text, **kwargs)
    if status == 401:
        return AuthenticationError(text, **kwargs)
    if status == 402:
        return PaymentRequiredError(text, **kwargs)
    if status == 403:
        return PermissionDeniedError(text, **kwargs)
    if status == 404:
        return NotFoundError(text, **kwargs)
    if status == 429:
        return RateLimitError(text, retry_after=retry_after, **kwargs)
    if status >= 500:
        return ServerError(text, **kwargs)
    return LifeAstroError(text, **kwargs)
