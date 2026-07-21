"""Smoke test: actually download a small public file."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoink.core.engine import DownloadEngine

# Cloudflare speed test endpoint — supports arbitrary size, stable, CORS-open.
TEST_URL = "https://speed.cloudflare.com/__down?bytes=10240"  # exactly 10 KiB


@pytest.mark.asyncio
async def test_head_returns_metadata() -> None:
    engine = DownloadEngine(connections=1)
    info = await engine.head(TEST_URL)
    assert info.total_size == 10240


@pytest.mark.asyncio
async def test_stream_downloads_file(tmp_path: Path) -> None:
    engine = DownloadEngine(connections=1)
    output = tmp_path / "blob.bin"
    last_tick = 0
    async for tick in engine.stream(TEST_URL, output):
        assert tick.downloaded >= last_tick
        last_tick = tick.downloaded

    assert output.exists()
    assert output.stat().st_size == 10240
