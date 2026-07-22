"""Minimal HTTP server with Range support for resume integration tests.

Stdlib http.server doesn't honor Range in Python 3.12 (it advertises
'Accept-Ranges: bytes' but ignores the Range header). This handler does it right.
"""

from __future__ import annotations

import argparse
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


class RangeHTTPRequestHandler(BaseHTTPRequestHandler):
    server_version = "yoink-test/1.0"
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        self._handle()

    def do_HEAD(self) -> None:  # noqa: N802
        self._handle(head_only=True)

    def _handle(self, head_only: bool = False) -> None:  # noqa: PLR0915
        path = unquote(urlparse(self.path).path).lstrip("/")
        full_path = Path(self.server.servedir) / path  # type: ignore[attr-defined]
        if not full_path.is_file():
            self._send_error(HTTPStatus.NOT_FOUND, f"not found: {path}")
            return

        file_size = full_path.stat().st_size
        range_header = self.headers.get("Range")
        chunk_delay = getattr(self.server, "chunk_delay", 0.0)  # type: ignore[attr-defined]

        if range_header and range_header.startswith("bytes="):
            try:
                start_str, end_str = range_header[6:].split("-", 1)
                start = int(start_str) if start_str else 0
                end = int(end_str) if end_str else file_size - 1
            except ValueError:
                self._send_error(HTTPStatus.RANGE_NOT_SATISFIABLE, "bad range")
                return

            if start > end or start >= file_size:
                self._send_error(HTTPStatus.RANGE_NOT_SATISFIABLE, "out of range")
                return
            end = min(end, file_size - 1)
            length = end - start + 1

            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(length))
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("ETag", f'"{file_size}-{full_path.stat().st_mtime_ns}"')
            self.end_headers()

            if not head_only:
                with full_path.open("rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(64 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                        if chunk_delay:
                            time.sleep(chunk_delay)
        else:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(file_size))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("ETag", f'"{file_size}-{full_path.stat().st_mtime_ns}"')
            self.end_headers()

            if not head_only:
                with full_path.open("rb") as f:
                    while chunk := f.read(64 * 1024):
                        self.wfile.write(chunk)
                        if chunk_delay:
                            time.sleep(chunk_delay)

    def _send_error(self, status: HTTPStatus, msg: str) -> None:
        body = msg.encode() + b"\n"
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass  # silence


def serve(directory: str, port: int, chunk_delay: float = 0.0) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), RangeHTTPRequestHandler)
    server.servedir = directory  # type: ignore[attr-defined]
    server.chunk_delay = chunk_delay  # type: ignore[attr-defined]
    throttled = f" (delay {chunk_delay * 1000:.0f}ms/chunk)" if chunk_delay else ""
    print(f"range-test server serving {directory} on http://127.0.0.1:{port}{throttled}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True)
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument(
        "--chunk-delay", type=float, default=0.0, help="Seconds to sleep per 64KB chunk"
    )
    args = parser.parse_args()
    serve(args.dir, args.port, args.chunk_delay)
