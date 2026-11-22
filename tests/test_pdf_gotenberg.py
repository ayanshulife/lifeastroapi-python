"""The Gotenberg engine sends the right form, against a local stand-in (no Docker needed)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time
from collections.abc import Iterator
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from lifeastroapi import pdf


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["content-length"]))
        prefix = f"Content-Type: {self.headers['content-type']}\r\n\r\n".encode()
        fields: dict[str, str] = {}
        files: dict[str, str] = {}
        for part in BytesParser(policy=HTTP).parsebytes(prefix + body).iter_parts():
            content = part.get_payload(decode=True)
            assert isinstance(content, bytes)
            name = part.get_filename()
            if name:
                files[name] = content.decode("utf-8")
            else:
                key = str(part.get_param("name", header="content-disposition"))
                fields[key] = content.decode("utf-8")
        if "slow" in files.get("index.html", ""):
            time.sleep(1)
        status, out = (
            200,
            b"%PDF-test "
            + json.dumps(
                {"fields": fields, "files": files, "auth": self.headers.get("authorization")}
            ).encode(),
        )
        if self.path == "/html/forms/chromium/convert/html":
            out = b"<html>a proxy page</html>"
        elif self.path not in (
            "/forms/chromium/convert/html",
            "/gotenberg/forms/chromium/convert/html",
        ):
            status, out = 404, b"not found"
        self.send_response(status)
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        with contextlib.suppress(OSError):  # the client may have given up
            self.wfile.write(out)


@pytest.fixture(scope="module")
def url() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def echo(data: bytes) -> dict[str, Any]:
    assert data.startswith(b"%PDF-test ")
    decoded: dict[str, Any] = json.loads(data[10:])
    return decoded


def test_sends_the_html_and_the_page_geometry(url: str) -> None:
    engine = pdf.GotenbergPdfEngine(
        f"{url}/gotenberg/", headers={"Authorization": "Basic dXNlcjpwYXNz"}
    )
    options = pdf.PdfOptions(
        format="Letter", landscape=True, margin=pdf.PdfMargin(top="25.4mm", left="1in")
    )
    sent = echo(engine.html_to_pdf("<p>नमस्ते</p>", options))
    assert sent["fields"] == {
        "paperWidth": "11",
        "paperHeight": "8.5",
        "marginTop": "1",
        "marginBottom": "0",
        "marginLeft": "1",
        "marginRight": "0",
        "preferCssPageSize": "true",
        "printBackground": "true",
        "landscape": "false",
        "scale": "1",
    }
    css = (
        "@page { margin-top: 25.4mm !important; margin-left: 1in !important; "
        "size: 11in 8.5in !important; }\n"
    )
    assert sent["files"] == {"index.html": f"<p>नमस्ते</p>\n<style>{css}</style>"}
    assert sent["auth"] == "Basic dXNlcjpwYXNz"


def test_sends_header_and_footer_as_documents(url: str) -> None:
    options = pdf.PdfOptions(
        display_header_footer=True, header_template="<b>H</b>", footer_template="<i>F</i>"
    )
    sent = echo(pdf.GotenbergPdfEngine(url).html_to_pdf("<p>x</p>", options))
    assert sent["fields"]["preferCssPageSize"] == "false"
    assert list(sent["files"]) == ["index.html", "header.html", "footer.html"]
    assert '<body style="margin:0"><b>H</b></body>' in sent["files"]["header.html"]


def test_a_report_prints_through_gotenberg(url: str) -> None:
    sent = echo(pdf.kundli_lite_pdf({"Locale": "pa"}, engine=pdf.GotenbergPdfEngine(url)))
    assert '<html lang="pa">' in sent["files"]["index.html"]


@pytest.mark.parametrize(
    ("path", "message"), [("/missing", "Gotenberg returned 404"), ("/html", "no PDF data")]
)
def test_failures_raise(url: str, path: str, message: str) -> None:
    with pytest.raises(pdf.PdfError, match=message) as caught:
        pdf.GotenbergPdfEngine(url + path).html_to_pdf("x")
    assert caught.value.code == "gotenberg_failed"


def test_an_unreachable_service_raises() -> None:
    with pytest.raises(pdf.PdfError) as caught:
        pdf.GotenbergPdfEngine("http://127.0.0.1:9").html_to_pdf("x")
    assert caught.value.code == "gotenberg_failed"
    with pytest.raises(ValueError):
        pdf.GotenbergPdfEngine("localhost:3000")


def test_timeout(url: str) -> None:
    options = pdf.PdfOptions(timeout=0.1, print_timeout=0.1)
    with pytest.raises(pdf.PdfError) as caught:
        pdf.GotenbergPdfEngine(url).html_to_pdf("slow", options)
    assert caught.value.code == "timeout"


def test_cancel(url: str) -> None:
    stop = threading.Event()
    threading.Timer(0.1, stop.set).start()
    started = time.monotonic()
    with pytest.raises(pdf.PdfError) as caught:
        pdf.GotenbergPdfEngine(url).html_to_pdf("slow", cancel=stop)
    assert caught.value.code == "cancelled"
    assert time.monotonic() - started < 0.8


def test_async_and_its_cancellation(url: str) -> None:
    async def run() -> None:
        async with pdf.GotenbergPdfEngine(url) as engine:
            assert echo(await engine.html_to_pdf_async("x"))["files"] == {"index.html": "x"}
            job = asyncio.ensure_future(engine.html_to_pdf_async("slow"))
            await asyncio.sleep(0.1)
            job.cancel()
            with pytest.raises(asyncio.CancelledError):
                await job

    asyncio.run(run())
