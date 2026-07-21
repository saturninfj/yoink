"""DownloadEngine: orchestrates multi-segment downloads.

Day 2 MVP: single-segment streaming download.
Day 3 will swap in true multi-segment parallelism with the same public API.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from yoink.core.http_client import HttpClient, ResponseInfo

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
        self._http = HttpClient(
            max_connections=max(connections, 4),
            user_agent=user_agent or "yoink/0.0.1 (+https://github.com/saturninfj/yoink)",
            headers=extra_headers,
        )

    async def head(self, url: str) -> ResponseInfo:
        """Probe URL metadata without downloading body."""
        async with self._http as _:
            return await self._http.probe(url)

    async def stream(
        self,
        url: str,
        output: Path,
    ) -> AsyncIterator[DownloadTick]:
        """Download URL to output path, yielding progress ticks.

        Day 2: single-segment stream. The output file is written sequentially.
        Day 3 will replace internals with multi-segment parallelism.
        """
        # Probe first (re-opens client because head() closes it).
        info = await self.head(url)

        output.parent.mkdir(parents=True, exist_ok=True)
        downloaded = 0
        last_tick = asyncio.get_event_loop().time()
        last_bytes = 0
        speed_bps: float | None = None

        async with self._http as _:
            with output.open("wb") as f:
                async for chunk in self._http.stream_range(url, start=0, end=None):
                    f.write(chunk)
                    downloaded += len(chunk)

                    now = asyncio.get_event_loop().time()
                    elapsed = now - last_tick
                    if elapsed >= TICK_INTERVAL_SEC:
                        speed_bps = (downloaded - last_bytes) / elapsed
                        last_tick = now
                        last_bytes = downloaded

                    yield DownloadTick(
                        downloaded=downloaded,
                        total=info.total_size,
                        speed_bps=speed_bps,
                    )

        # Final tick
        yield DownloadTick(
            downloaded=downloaded,
            total=info.total_size,
            speed_bps=speed_bps,
        )
