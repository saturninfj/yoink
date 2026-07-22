"""HTTP client wrapper around httpx for ranged downloads."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

DEFAULT_USER_AGENT = "yoink/0.0.1 (+https://github.com/saturninfj/yoink)"
DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

HTTP_BAD = 400
HTTP_PARTIAL_CONTENT = 206


@dataclass(frozen=True)
class ResponseInfo:
    """Metadata from a HEAD/GET probe."""

    final_url: str
    total_size: int | None
    accepts_ranges: bool
    suggested_filename: str
    etag: str | None
    last_modified: str | None


class HttpClient:
    """Thin async wrapper around httpx.AsyncClient with HTTP/2 enabled."""

    def __init__(
        self,
        max_connections: int = 32,
        user_agent: str = DEFAULT_USER_AGENT,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_connections,
        )
        base_headers = {"User-Agent": user_agent}
        if headers:
            base_headers.update(headers)
        self._base_headers = base_headers
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> HttpClient:
        self._client = httpx.AsyncClient(
            http2=True,
            follow_redirects=True,
            timeout=DEFAULT_TIMEOUT,
            limits=self._limits,
            headers=self._base_headers,
        )
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HttpClient used outside 'async with' block")
        return self._client

    async def probe(self, url: str) -> ResponseInfo:
        """Probe URL: try Range request first (also confirms range support).

        Returns Content-Length from full file (not the 1-byte response body).
        """
        assert self._client is not None
        # GET with Range: bytes=0-0. Server response tells us:
        #  - 206 + Content-Range → ranges supported, real size in `bytes 0-0/TOTAL`
        #  - 200 OK → ranges NOT supported, size in Content-Length
        resp = await self._client.get(url, headers={"Range": "bytes=0-0"})
        if resp.status_code >= HTTP_BAD:
            # Final fallback: plain HEAD (some servers refuse Range on HEAD).
            resp = await self._client.head(url)
        resp.raise_for_status()
        return _response_info(resp)

    async def stream_range(
        self,
        url: str,
        start: int,
        end: int | None,
    ) -> AsyncIterator[bytes]:
        """Yield bytes for the byte-range [start, end] (inclusive).

        If end is None, streams from start to EOF.
        """
        range_header = f"bytes={start}-" if end is None else f"bytes={start}-{end}"
        async with self.client.stream("GET", url, headers={"Range": range_header}) as resp:
            if resp.status_code not in (200, 206):
                raise httpx.HTTPStatusError(
                    f"unexpected status {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
            async for chunk in resp.aiter_bytes():
                yield chunk


def _response_info(resp: httpx.Response) -> ResponseInfo:
    """Build ResponseInfo from an HTTP response, normalising server quirks."""
    accepts_ranges = resp.headers.get("Accept-Ranges", "").lower() == "bytes"
    # Even without Accept-Ranges header, a 206 response implies range support.
    if resp.status_code == HTTP_PARTIAL_CONTENT:
        accepts_ranges = True

    total_size: int | None
    if accepts_ranges and "Content-Range" in resp.headers:
        # Format: "bytes START-END/TOTAL"
        cr = resp.headers["Content-Range"]
        try:
            total_size = int(cr.split("/", 1)[1])
        except (ValueError, IndexError):
            total_size = None
    elif "Content-Length" in resp.headers:
        try:
            total_size = int(resp.headers["Content-Length"])
        except ValueError:
            total_size = None
    else:
        total_size = None

    return ResponseInfo(
        final_url=str(resp.url),
        total_size=total_size,
        accepts_ranges=accepts_ranges,
        suggested_filename=_filename_from_response(resp),
        etag=resp.headers.get("ETag"),
        last_modified=resp.headers.get("Last-Modified"),
    )


def _filename_from_response(resp: httpx.Response) -> str:
    """Best-effort filename extraction. Order: Content-Disposition > URL path > 'index.bin'."""
    cd: str = resp.headers.get("Content-Disposition", "")
    if "filename=" in cd:
        # Naive parser, good enough for now.
        for piece in cd.split(";"):
            stripped = piece.strip()
            if stripped.lower().startswith("filename="):
                name: str = stripped.split("=", 1)[1].strip().strip('"')
                if name:
                    return name

    path: str = resp.url.path
    if path and path != "/":
        extracted = path.rsplit("/", 1)[-1]
        if extracted:
            return extracted

    return "index.bin"
