"""DownloadEngine: orchestrates multi-segment parallel downloads.

Implements IDM-style in-half division rule with sparse-file pre-allocation:
each segment writes to its byte range directly, no concat at end.

Optional StateStore persists progress every ~1s for resume after Ctrl-C / crash.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import anyio

from yoink.core.http_client import HttpClient, ResponseInfo
from yoink.core.resume import assert_resumable
from yoink.core.segment import Segment, SegmentStatus, split_into_segments
from yoink.core.state import StateStore

DEFAULT_CHUNK_SIZE = 64 * 1024  # 64 KiB per write to disk
DEFAULT_CONNECTIONS = 8
MAX_CONNECTIONS = 32
TICK_INTERVAL_SEC = 0.5
CHECKPOINT_INTERVAL_SEC = 1.0
DEFAULT_USER_AGENT = "yoink/0.0.1 (+https://github.com/saturninfj/yoink)"


def _file_is_pre_allocated(path: Path, expected_size: int) -> bool:
    """True if path exists with exactly expected_size bytes."""
    return path.exists() and path.stat().st_size == expected_size


STATUS_DOWNLOADING = "downloading"
STATUS_PAUSED = "paused"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class DownloadTick:
    """Progress update emitted during a download."""

    downloaded: int
    total: int | None
    speed_bps: float | None = None


class DownloadEngine:
    """Orchestrates HTTP downloads with optional state persistence."""

    def __init__(
        self,
        connections: int = DEFAULT_CONNECTIONS,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        user_agent: str | None = None,
        extra_headers: dict[str, str] | None = None,
        state_store: StateStore | None = None,
    ) -> None:
        if not 1 <= connections <= MAX_CONNECTIONS:
            raise ValueError(f"connections must be 1-{MAX_CONNECTIONS}, got {connections}")
        self._connections = connections
        self._chunk_size = chunk_size
        self._user_agent = user_agent or DEFAULT_USER_AGENT
        self._extra_headers = extra_headers or {}
        self._state = state_store

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
        """Fresh download to output path. Yields progress ticks.

        If state_store was provided, registers the download and checkpoints
        progress every ~1s so it can be resumed via `resume(download_id)`.
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

        async for tick in self._run_multi_segment(
            url=url,
            output=output,
            info=info,
            download_id=None,
            segments=None,
        ):
            yield tick

    async def resume(self, download_id: int) -> AsyncIterator[DownloadTick]:
        """Resume a previously checkpointed download by ID.

        Validates ETag/Last-Modified haven't changed, then continues from
        saved segment positions.
        """
        if self._state is None:
            raise RuntimeError("resume() requires a StateStore")

        record = self._state.get_download(download_id)
        if record is None:
            raise ValueError(f"no download with id={download_id}")
        if record.status == STATUS_COMPLETED:
            raise ValueError(f"download {download_id} already completed")

        stored_segments = self._state.load_segments(download_id)

        # Re-probe to validate freshness.
        fresh_info = await self.head(record.url)
        assert_resumable(
            fresh=fresh_info,
            stored_etag=record.etag,
            stored_last_modified=record.last_modified,
        )

        # Prefer fresh info (handles redirects, refreshed ETag).
        info = fresh_info if fresh_info.total_size == record.total_size else fresh_info
        output = Path(record.output_path)

        async for tick in self._run_multi_segment(
            url=record.url,
            output=output,
            info=info,
            download_id=download_id,
            segments=stored_segments,
        ):
            yield tick

    async def _run_multi_segment(  # noqa: PLR0915
        self,
        url: str,
        output: Path,
        info: ResponseInfo,
        download_id: int | None,
        segments: list[Segment] | None,
    ) -> AsyncIterator[DownloadTick]:
        """Core multi-segment loop. Used by both fresh downloads and resumes."""
        total = info.total_size
        assert total is not None and total > 0

        is_resume = segments is not None and download_id is not None
        if not is_resume:
            n_conns = min(self._connections, total)
            segments = split_into_segments(total_size=total, n_segments=n_conns)
            download_id = self._register_download(
                url=url,
                info=info,
                output=output,
                segments=segments,
            )

        assert segments is not None
        assert download_id is not None

        # Pre-allocate sparse file (skip if it already exists with right size).
        output.parent.mkdir(parents=True, exist_ok=True)
        if not _file_is_pre_allocated(output, total):  # noqa: ASYNC240
            with output.open("wb") as f:
                f.truncate(total)

        progress = _ProgressState(
            total=total,
            initial=sum(s.downloaded for s in segments),
        )

        done = asyncio.Event()
        cancel_event = asyncio.Event()
        first_error: BaseException | None = None

        async def runner() -> None:
            nonlocal first_error
            try:
                # IMPORTANT: http client must outlive all tasks, so the task
                # group must be nested INSIDE `async with http:`.
                http = self._make_client(max_conns=self._connections)
                async with http:
                    async with anyio.create_task_group() as tg:
                        for seg in segments:
                            tg.start_soon(
                                self._download_segment,
                                http,
                                url,
                                output,
                                seg,
                                progress,
                            )
                        if self._state is not None:
                            tg.start_soon(
                                self._heartbeat,
                                download_id,
                                segments,
                                progress,
                                cancel_event,
                            )
            except BaseException as exc:
                first_error = exc
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
            if first_error is not None:
                raise first_error
            await runner_task

            tick = progress.snapshot(force=True)
            if tick.downloaded != last_emit:
                yield tick

            # Mark completed.
            self._finalize(download_id, segments, progress, STATUS_COMPLETED)
        except asyncio.CancelledError:
            cancel_event.set()
            runner_task.cancel()
            with contextlib.suppress(BaseException):
                await runner_task
            self._finalize(download_id, segments, progress, STATUS_PAUSED)
            yield progress.snapshot(force=True)
            raise
        except BaseException as exc:
            self._finalize(download_id, segments, progress, STATUS_FAILED, str(exc))
            raise

    async def _download_segment(
        self,
        http: HttpClient,
        url: str,
        output: Path,
        seg: Segment,
        progress: _ProgressState,
    ) -> None:
        """Download one segment's range sequentially to its file offset.

        Starts from seg.current_byte (set by resume) instead of seg.start_byte.
        """
        assert seg.current_byte is not None
        with output.open("r+b") as f:
            f.seek(seg.current_byte)
            seg.status = SegmentStatus.DOWNLOADING
            start = seg.current_byte
            async for chunk in http.stream_range(url, start=start, end=seg.end_byte):
                f.write(chunk)
                seg.advance(len(chunk))
                progress.add(len(chunk))
        seg.status = SegmentStatus.COMPLETED

    async def _heartbeat(
        self,
        download_id: int,
        segments: list[Segment],
        progress: _ProgressState,
        cancel: asyncio.Event,
    ) -> None:
        """Periodic checkpoint. Exits when all segments complete or on cancel."""
        while not cancel.is_set():
            try:
                await asyncio.sleep(CHECKPOINT_INTERVAL_SEC)
            except asyncio.CancelledError:
                return
            if cancel.is_set():
                return
            assert self._state is not None
            self._state.checkpoint(
                download_id=download_id,
                segments=segments,
                downloaded_size=progress.downloaded,
                status=STATUS_DOWNLOADING,
            )
            if all(s.is_complete for s in segments):
                return

    def _register_download(
        self,
        url: str,
        info: ResponseInfo,
        output: Path,
        segments: list[Segment],
    ) -> int:
        """Create download + segment rows in state DB (if available)."""
        if self._state is None:
            return -1
        download_id = self._state.create_download(
            url=url,
            final_url=info.final_url,
            output_path=str(output),
            status=STATUS_DOWNLOADING,
            total_size=info.total_size,
            connections=self._connections,
            etag=info.etag,
            last_modified=info.last_modified,
        )
        self._state.add_segments(download_id, segments)
        return download_id

    def _finalize(
        self,
        download_id: int,
        segments: list[Segment],
        progress: _ProgressState,
        status: str,
        error: str | None = None,
    ) -> None:
        """Final state write after completion / pause / failure."""
        if self._state is None or download_id < 0:
            return
        self._state.checkpoint(
            download_id=download_id,
            segments=segments,
            downloaded_size=progress.downloaded,
            status=status,
            error=error,
        )

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
    Supports resume by initialising downloaded with the sum of segment
    already-downloaded bytes.
    """

    __slots__ = ("total", "_downloaded", "_last_emit", "_loop_time")

    def __init__(self, total: int, initial: int = 0) -> None:
        self.total = total
        self._downloaded = initial
        self._last_emit = initial
        self._loop_time = asyncio.get_event_loop().time()

    def add(self, n: int) -> None:
        self._downloaded += n

    @property
    def downloaded(self) -> int:
        return self._downloaded

    def snapshot(self, force: bool = False) -> DownloadTick:
        now = asyncio.get_event_loop().time()
        elapsed = now - self._loop_time
        downloaded = self._downloaded
        speed = (downloaded - self._last_emit) / elapsed if elapsed > 0 else None
        if not force:
            self._last_emit = downloaded
            self._loop_time = now
        return DownloadTick(downloaded=downloaded, total=self.total, speed_bps=speed)
