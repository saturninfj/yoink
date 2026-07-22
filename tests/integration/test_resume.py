"""Resume integration tests against a local range-enabled HTTP server."""

from __future__ import annotations

import asyncio
import contextlib
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from yoink.core.engine import DownloadEngine
from yoink.core.state import StateStore

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_SCRIPT = REPO_ROOT / "scripts" / "recon" / "range_server.py"
TEST_FILE_SIZE = 50 * 1024 * 1024  # 50 MiB


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory):
    """Run range_server.py with throttle to keep downloads slow enough to interrupt."""
    workdir = tmp_path_factory.mktemp("range-server-data")
    test_file = workdir / "blob.bin"
    test_file.write_bytes(b"yoink-test-" * (TEST_FILE_SIZE // 11 + 1))
    test_file.write_bytes(test_file.read_bytes()[:TEST_FILE_SIZE])
    port = _free_port()
    proc = subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            str(SERVER_SCRIPT),
            "--dir",
            str(workdir),
            "--port",
            str(port),
            "--chunk-delay",
            "0.005",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait for server ready
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect(("127.0.0.1", port))
                break
        except OSError:
            time.sleep(0.1)
    yield port, test_file
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def fresh_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point StateStore at a temp DB to avoid polluting ~/.yoink."""
    db = tmp_path / "state.db"
    monkeypatch.setattr("yoink.core.state.DEFAULT_DB_PATH", db)
    return db


@pytest.mark.asyncio
async def test_download_completes(
    server: tuple[int, Path],
    fresh_state: Path,
    tmp_path: Path,
) -> None:
    port, src = server
    url = f"http://127.0.0.1:{port}/{src.name}"
    output = tmp_path / "out.bin"

    state = StateStore()
    engine = DownloadEngine(connections=2, state_store=state)
    async for _ in engine.stream(url, output):
        pass
    state.close()

    assert output.exists()
    assert output.stat().st_size == src.stat().st_size
    assert output.read_bytes() == src.read_bytes()

    # State marked completed.
    state2 = StateStore()
    record = next(state2.list_downloads())
    assert record.status == "completed"
    assert record.downloaded_size == src.stat().st_size


@pytest.mark.asyncio
async def test_resume_after_cancel(
    server: tuple[int, Path],
    fresh_state: Path,
    tmp_path: Path,
) -> None:
    port, src = server
    url = f"http://127.0.0.1:{port}/{src.name}"
    output = tmp_path / "out.bin"

    state = StateStore()
    engine = DownloadEngine(connections=2, state_store=state)

    # Start download, cancel mid-way.
    task = asyncio.create_task(_drain(engine, url, output))
    await asyncio.sleep(1.0)  # let it download a bit
    task.cancel()
    with contextlib.suppress(BaseException):
        await task
    state.close()

    # Verify partial state.
    state2 = StateStore()
    record = next(state2.list_downloads())
    assert record.status == "paused"
    assert 0 < record.downloaded_size < src.stat().st_size
    download_id = record.id
    state2.close()

    # Resume.
    state3 = StateStore()
    engine2 = DownloadEngine(connections=2, state_store=state3)
    async for _ in engine2.resume(download_id):
        pass
    state3.close()

    assert output.exists()
    assert output.stat().st_size == src.stat().st_size
    assert output.read_bytes() == src.read_bytes()

    # Final state: completed.
    state4 = StateStore()
    record2 = state4.get_download(download_id)
    assert record2 is not None
    assert record2.status == "completed"
    state4.close()


async def _drain(engine: DownloadEngine, url: str, output: Path) -> None:
    async for _ in engine.stream(url, output):
        pass
