from __future__ import annotations

import argparse
import errno
import json
import mimetypes
import re
import secrets
import tempfile
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlsplit

from . import __version__
from .latex import FORMATS, latex_source, standalone_source
from .model import Diagram, DiagramError, templates
from .render import save_pdf, save_raster, svg_document

APP_NAME = "Feynman Diagram Studio Web"
DEFAULT_PORT = 8765
MAX_REQUEST_BYTES = 2 * 1024 * 1024
STATIC_FILES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/app.css": "app.css",
    "/app.js": "app.js",
    "/favicon.svg": "favicon.svg",
    "/midnight-mark.svg": "midnight-mark.svg",
    "/DejaVuSerif.woff2": "DejaVuSerif.woff2",
}


def _asset(name: str) -> bytes:
    return files("feynman_studio").joinpath("web", name).read_bytes()


def _filename(title: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9-]+", "-", title).strip("-").lower()
    return name or "diagram"


class WebAppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int]):
        self.token = secrets.token_urlsafe(24)
        super().__init__(address, WebAppHandler)


class WebAppHandler(BaseHTTPRequestHandler):
    server: WebAppServer

    def log_message(self, _format: str, *args: Any) -> None:
        return

    def _headers(self, content_type: str, length: int, *, download: str | None = None) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' blob: data:; "
            "style-src 'self'; script-src 'self'; connect-src 'self'; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
        )
        if download:
            self.send_header("Content-Disposition", 'attachment; filename="{}"'.format(download))

    def _send(self, status: HTTPStatus, data: bytes, content_type: str, *, download: str | None = None) -> None:
        self.send_response(status)
        self._headers(content_type, len(data), download=download)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status: HTTPStatus, value: Any) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self._send(status, data, "application/json; charset=utf-8")

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json(status, {"error": message})

    def _payload(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise DiagramError("The request body is missing.")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise DiagramError("The request length is invalid.") from exc
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise DiagramError("The project is too large.")
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DiagramError("The request is not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise DiagramError("The request must contain an object.")
        return payload

    def _document(self, payload: dict[str, Any]) -> Diagram:
        raw = payload.get("diagram")
        if not isinstance(raw, dict):
            raise DiagramError("The request does not contain a diagram.")
        return Diagram.from_dict(raw)

    def _authorized(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-FDS-Token", ""), self.server.token)

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/bootstrap":
            self._json(
                HTTPStatus.OK,
                {
                    "version": __version__,
                    "token": self.server.token,
                    "templates": [document.to_dict() for document in templates()],
                    "latexFormats": [
                        {"value": option.value, "label": option.label} for option in FORMATS
                    ],
                },
            )
            return
        asset = STATIC_FILES.get(path)
        if asset is None:
            self._error(HTTPStatus.NOT_FOUND, "Not found.")
            return
        try:
            data = _asset(asset)
        except FileNotFoundError:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "A web application asset is missing.")
            return
        content_type = mimetypes.guess_type(asset)[0] or "application/octet-stream"
        if asset.endswith((".html", ".css", ".js")):
            content_type += "; charset=utf-8"
        self._send(HTTPStatus.OK, data, content_type)

    def do_POST(self) -> None:
        if not self._authorized():
            self._error(HTTPStatus.FORBIDDEN, "This request did not come from the editor.")
            return
        path = urlsplit(self.path).path
        if path == "/api/shutdown":
            self._json(HTTPStatus.OK, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        try:
            payload = self._payload()
            document = self._document(payload)
            if path == "/api/validate":
                self._json(HTTPStatus.OK, {"diagram": document.to_dict()})
            elif path == "/api/latex":
                self._latex(document, payload)
            elif path == "/api/export":
                self._export(document, payload)
            else:
                self._error(HTTPStatus.NOT_FOUND, "Not found.")
        except DiagramError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except (OSError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "The operation could not be completed.")

    def _latex(self, document: Diagram, payload: dict[str, Any]) -> None:
        format_name = payload.get("format", "tikz-feynman")
        if not isinstance(format_name, str):
            raise DiagramError("The LaTeX format is invalid.")
        self._json(
            HTTPStatus.OK,
            {
                "source": latex_source(document, format_name),
                "standalone": standalone_source(document, format_name),
            },
        )

    def _export(self, document: Diagram, payload: dict[str, Any]) -> None:
        format_name = payload.get("format", "svg")
        ppi = payload.get("ppi", 600)
        transparent = payload.get("transparent", False)
        if format_name not in ("svg", "pdf", "png", "jpg"):
            raise DiagramError("The export format is invalid.")
        if ppi not in (300, 600, 1200):
            raise DiagramError("The export resolution is invalid.")
        if not isinstance(transparent, bool):
            raise DiagramError("The transparency setting is invalid.")
        name = _filename(document.title) + "." + format_name
        if format_name == "svg":
            data = svg_document(document, transparent).encode("utf-8")
            self._send(HTTPStatus.OK, data, "image/svg+xml; charset=utf-8", download=name)
            return
        with tempfile.TemporaryDirectory(prefix="fds-web-export-") as temporary:
            output = Path(temporary) / name
            if format_name == "pdf":
                save_pdf(document, output, ppi)
            else:
                save_raster(document, output, ppi, transparent and format_name == "png")
            data = output.read_bytes()
        content_type = {
            "pdf": "application/pdf",
            "png": "image/png",
            "jpg": "image/jpeg",
        }[format_name]
        self._send(HTTPStatus.OK, data, content_type, download=name)


def create_server(host: str = "127.0.0.1", port: int = 8765) -> WebAppServer:
    return WebAppServer((host, port))


def _create_server(host: str, port: int, allow_fallback: bool) -> tuple[WebAppServer, bool]:
    try:
        return create_server(host, port), False
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE or not allow_fallback:
            raise
        return create_server(host, 0), True


def _smoke_test() -> None:
    for name in STATIC_FILES.values():
        if not _asset(name):
            raise RuntimeError("Web application asset is empty: " + name)
    if len(templates()) != 13:
        raise RuntimeError("The web template library is incomplete.")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run Feynman Diagram Studio in a web browser.")
    parser.add_argument("--host", default="127.0.0.1", help="Address to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, help="Port to bind (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the editor automatically")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    options = parser.parse_args(argv)
    if options.smoke_test:
        _smoke_test()
        return
    requested_port = options.port if options.port is not None else DEFAULT_PORT
    try:
        server, used_fallback = _create_server(
            options.host, requested_port, allow_fallback=options.port is None
        )
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            parser.error("Port {} is already in use; choose another with --port.".format(requested_port))
        raise
    port = server.server_address[1]
    browser_host = "127.0.0.1" if options.host in ("0.0.0.0", "::") else options.host
    url = "http://{}:{}/".format(browser_host, port)
    if used_fallback:
        print("Port {} is already in use; using port {} instead.".format(requested_port, port))
    print(APP_NAME + " is running at " + url)
    print("Press Ctrl+C or choose File → Stop web app to exit.")
    if not options.no_browser:
        opener = threading.Timer(0.2, lambda: webbrowser.open(url))
        opener.daemon = True
        opener.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
