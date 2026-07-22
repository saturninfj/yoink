"""DownloadEngine: orchestrates multi-segment parallel downloads.

Implements IDM-style in-half division rule with sparse-file pre-allocation:
each segment writes to its byte range directly, no concat at end.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import anyio

from yoink.core.http_client import HttpClient, ResponseInfo
from yoink.core.segment import Segment, SegmentStatus, split_into_segments

DEFAULT_CHUNK_SIZE = 64 * 1024  # 64 KiB per write to disk
DEFAULT_CONNECTIONS = 8
MAX_CONNECTIONS = 32
TICK_INTERVAL_SEC = 0.5


@dataclass(frozen=True)
class DownloadTick:
    """Progress update emitted during a download."""

    downloaded: int
    total: int | None
    speed_bps: float | None = None


class DownloadEngine:
    """Orchestrates HTTP downloads.

    Usage::

        engine = DownloadEngine(connections=8)
        info = await engine.head(url)
        async for tick in engine.stream(url, output):
            ...
    """

    def __init__(
        self,
        connections: int = DEFAULT_CONNECTIONS,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        user_agent: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        if not 1 <= connections <= MAX_CONNECTIONS:
            raise ValueError(f"connections must be 1-{MAX_CONNECTIONS}, got {connections}")
        self._connections = connections
        self._chunk_size = chunk_size
        self._user_agent = user_agent or "yoink/0.0.1 (+https://github.com/saturninfj/yoink)"
        self._extra_headers = extra_headers or {}

    def _make_client(self, max_conns: int) -> HttpClient:
        return HttpClient(
            max_connections=max_conns,
            user_agent=self._user_agent,
            headers=self._extra_headers,
        )

    async def head(self, url: str) -> ResponseInfo:
        """Probe URL metadata without downloading body."""
        async with self._make_client(max_conns=4) as http:
            return await http.probe(url)

    async def stream(
        self,
        url: str,
        output: Path,
    ) -> AsyncIterator[DownloadTick]:
        """Download URL to output path, yielding progress ticks.

        If server supports ranges and total size is known, splits into
        `self._connections` parallel segments writing to disjoint byte ranges
        of a pre-allocated sparse file. Otherwise falls back to single-segment
        sequential streaming.
        """
        info = await self.head(url)

        if info.total_size is None or info.total_size == 0:
            async for tick in self._stream_unknown_size(url, output, info):
                yield tick
            return

        if not info.accepts_ranges:
            async for tick in self._stream_no_range(url, output, info):
                yield tick
            return

        async for tick in self._stream_multi_segment(url, output, info):
            yield tick

    async def _stream_multi_segment(
        self,
        url: str,
        output: Path,
        info: ResponseInfo,
    ) -> AsyncIterator[DownloadTick]:
        """Multi-segment parallel download via sparse-file writes."""
        total = info.total_size
        assert total is not None
        n_conns = min(self._connections, total)
        segments = split_into_segments(total_size=total, n_segments=n_conns)

        output.parent.mkdir(parents=True, exist_ok=True)
        # Pre-allocate sparse file (no actual disk usage until written).
        with output.open("wb") as f:
            f.truncate(total)

        progress = _ProgressState(total=total)
        done = asyncio.Event()

        async def runner() -> None:
            try:
                async with anyio.create_task_group() as tg:
                    http = self._make_client(max_conns=self._connections)
                    async with http:
                        for seg in segments:
                            tg.start_soon(self._download_segment, http, url, output, seg, progress)
            finally:
                done.set()

        runner_task = asyncio.create_task(runner())
        last_emit: float = 0.0

        try:
            while not done.is_set():
                await asyncio.sleep(TICK_INTERVAL_SEC)
                tick = progress.snapshot()
                yield tick
                last_emit = tick.downloaded

            # Propagate any exception from runner.
            await runner_task
            # Final tick.
            tick = progress.snapshot(force=True)
            if tick.downloaded != last_emit:
                yield tick
        except asyncio.CancelledError:
            runner_task.cancel()
            with contextlib.suppress(BaseException):
                await runner_task
            yield progress.snapshot(force=True)
            raise

    async def _download_segment(
        self,
        http: HttpClient,
        url: str,
        output: Path,
        seg: Segment,
        progress: _ProgressState,
    ) -> None:
        """Download one segment's byte range sequentially to its file offset."""
        # Each task opens its own fd; seek to seg.start_byte; write sequentially.
        with output.open("r+b") as f:
            f.seek(seg.start_byte)
            async for chunk in http.stream_range(url, start=seg.start_byte, end=seg.end_byte):
                f.write(chunk)
                seg.advance(len(chunk))
                progress.add(len(chunk))
        seg.status = SegmentStatus.COMPLETED

    async def _stream_unknown_size(
        self,
        url: str,
        output: Path,
        info: ResponseInfo,
    ) -> AsyncIterator[DownloadTick]:
        """Fallback: server gave no Content-Length. Sequential stream to disk."""
        output.parent.mkdir(parents=True, exist_ok=True)
        downloaded = 0
        async with self._make_client(max_conns=1) as http:
            with output.open("wb") as f:
                async for chunk in http.stream_range(url, start=0, end=None):
                    f.write(chunk)
                    downloaded += len(chunk)
                    yield DownloadTick(downloaded=downloaded, total=None)

    async def _stream_no_range(
        self,
        url: str,
        output: Path,
        info: ResponseInfo,
    ) -> AsyncIterator[DownloadTick]:
        """Fallback: server doesn't support Range. Single sequential stream."""
        total = info.total_size
        assert total is not None
        output.parent.mkdir(parents=True, exist_ok=True)
        downloaded = 0
        async with self._make_client(max_conns=1) as http:
            with output.open("wb") as f:
                async for chunk in http.stream_range(url, start=0, end=None):
                    f.write(chunk)
                    downloaded += len(chunk)
                    yield DownloadTick(downloaded=downloaded, total=total)


class _ProgressState:
    """Lock-free progress aggregation across segment tasks.

    asyncio is single-threaded so += operations between awaits are atomic.
    """

    __slots__ = ("total", "_downloaded", "_last_emit", "_loop_time")

    def __init__(self, total: int) -> None:
        self.total = total
        self._downloaded = 0
        self._last_emit = 0
        self._loop_time = asyncio.get_event_loop().time()

    def add(self, n: int) -> None:
        self._downloaded += n

    def snapshot(self, force: bool = False) -> DownloadTick:
        now = asyncio.get_event_loop().time()
        elapsed = now - self._loop_time
        downloaded = self._downloaded
        speed = (downloaded - self._last_emit) / elapsed if elapsed > 0 else None
        if not force:
            self._last_emit = downloaded
            self._loop_time = now
        return DownloadTick(downloaded=downloaded, total=self.total, speed_bps=speed)
