"""The Gotenberg engine."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from types import TracebackType

import httpx

from . import _js
from ._options import PdfError, PdfMargin, PdfOptions, check_cancelled, printable
from ._print_css import with_print_css

_Part = tuple[str, tuple[str, bytes, str]]


class GotenbergPdfEngine:
    """Prints through a `Gotenberg <https://gotenberg.dev>`_ service that you run.

    For servers that cannot run a browser. Start Gotenberg anywhere you control, for
    example ``docker run --rm -p 3000:3000 gotenberg/gotenberg:8``, then::

        engine = GotenbergPdfEngine("http://localhost:3000")
        pdf = kundli_lite_pdf(report, engine=engine)

    :param base_url: The Gotenberg base URL.
    :param headers: Extra request headers, for example basic auth.
    """

    def __init__(self, base_url: str, *, headers: Mapping[str, str] | None = None) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError(f"the Gotenberg URL must start with http:// or https://: {base_url}")
        self._endpoint = base_url.rstrip("/") + "/forms/chromium/convert/html"
        self._headers = dict(headers or {})

    def html_to_pdf(
        self,
        html: str,
        options: PdfOptions | None = None,
        *,
        cancel: threading.Event | None = None,
    ) -> bytes:
        """Print a complete HTML document to PDF bytes.

        :param cancel: Set this event from another thread to stop waiting for the service.
        :raises PdfError: The service failed, timed out, or the job was cancelled.
        """
        check_cancelled(cancel)
        options = options or PdfOptions()
        if cancel is None:
            return self._post(html, options)
        # A blocked socket read cannot be interrupted, so wait for it on another thread.
        done = threading.Event()
        result: list[bytes] = []
        failure: list[Exception] = []

        def post() -> None:
            try:
                result.append(self._post(html, options))
            except Exception as error:
                failure.append(error)
            finally:
                done.set()

        threading.Thread(target=post, name="lifeastroapi-gotenberg", daemon=True).start()
        while not done.wait(0.05):
            check_cancelled(cancel)
        if failure:
            raise failure[0]
        return result[0]

    async def html_to_pdf_async(self, html: str, options: PdfOptions | None = None) -> bytes:
        """:meth:`html_to_pdf` for ``asyncio`` code. Cancelling the task drops the request."""
        options = options or PdfOptions()
        fields, parts = _form(html, options)
        try:
            async with httpx.AsyncClient(timeout=_timeout(options)) as http:
                response = await http.post(
                    self._endpoint, data=fields, files=parts, headers=self._headers
                )
        except httpx.HTTPError as error:
            raise _transport_error(error) from error
        return _body(response)

    def close(self) -> None:
        """Nothing is held open between calls; here so engines can be used alike."""

    async def aclose(self) -> None:
        self.close()

    def __enter__(self) -> GotenbergPdfEngine:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    async def __aenter__(self) -> GotenbergPdfEngine:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def _post(self, html: str, options: PdfOptions) -> bytes:
        fields, parts = _form(html, options)
        try:
            with httpx.Client(timeout=_timeout(options)) as http:
                response = http.post(
                    self._endpoint, data=fields, files=parts, headers=self._headers
                )
        except httpx.HTTPError as error:
            raise _transport_error(error) from error
        return _body(response)


def _timeout(options: PdfOptions) -> httpx.Timeout:
    total = options.timeout + options.print_timeout
    return httpx.Timeout(total, connect=min(total, 10.0))


def _document(fragment: str) -> str:
    """Gotenberg wants the header and footer as complete HTML documents."""
    return (
        '<!doctype html><html><head><meta charset="utf-8"></head>'
        f'<body style="margin:0">{fragment}</body></html>'
    )


def _form(html: str, options: PdfOptions) -> tuple[dict[str, str], list[_Part]]:
    width, height = options.paper_inches()
    top, bottom, left, right = (options.margin or PdfMargin()).inches()
    number = _js.number_to_string
    fields = {
        "paperWidth": number(width),
        "paperHeight": number(height),
        "marginTop": number(top),
        "marginBottom": number(bottom),
        "marginLeft": number(left),
        "marginRight": number(right),
        "preferCssPageSize": "true" if options.uses_css_page_size() else "false",
        "printBackground": "true" if options.print_background else "false",
        # The orientation is already in the paper width and height.
        "landscape": "false",
        "scale": number(options.scale if options.scale is not None else 1.0),
    }
    documents = {"index.html": with_print_css(html, options)}
    if options.display_header_footer:
        documents["header.html"] = _document(options.header_template or "<span></span>")
        documents["footer.html"] = _document(options.footer_template or "<span></span>")
    parts = [
        ("files", (name, printable(text).encode("utf-8"), "text/html"))
        for name, text in documents.items()
    ]
    return fields, parts


def _transport_error(error: httpx.HTTPError) -> PdfError:
    code = "timeout" if isinstance(error, httpx.TimeoutException) else "gotenberg_failed"
    return PdfError(f"The Gotenberg request failed: {error}", code=code)


def _body(response: httpx.Response) -> bytes:
    if response.status_code != 200:
        raise PdfError(
            f"Gotenberg returned {response.status_code}: {response.text[:500]}",
            code="gotenberg_failed",
        )
    if not response.content.startswith(b"%PDF"):
        raise PdfError("Gotenberg returned no PDF data", code="gotenberg_failed")
    return response.content
