"""Integration tests for native messaging host (JSON-RPC over stdio)."""

from __future__ import annotations

import json
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_SCRIPT = REPO_ROOT / "scripts" / "recon" / "range_server.py"


def _send(proc: subprocess.Popen, msg: dict) -> None:
    payload = json.dumps(msg).encode("utf-8")
    assert proc.stdin is not None
    proc.stdin.write(struct.pack("<I", len(payload)))
    proc.stdin.write(payload)
    proc.stdin.flush()


def _recv(proc: subprocess.Popen, timeout: float = 5.0) -> dict | None:
    assert proc.stdout is not None
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = proc.stdout.read(4)
        if not raw:
            time.sleep(0.05)
            continue
        if len(raw) < 4:
            return None
        n = struct.unpack("<I", raw)[0]
        data = proc.stdout.read(n)
        if len(data) < n:
            return None
        return json.loads(data.decode("utf-8"))
    return None


def _spawn_host() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "yoink.browser.native_host"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


@pytest.fixture
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    return home


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory):
    workdir = tmp_path_factory.mktemp("native-host-data")
    test_file = workdir / "blob.bin"
    test_file.write_bytes(b"yoink-test-" * 200000)  # ~2.4 MiB
    port = _free_port()
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, str(SERVER_SCRIPT), "--dir", str(workdir), "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 5
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            try:
                s.connect(("127.0.0.1", port))
                break
            except OSError:
                time.sleep(0.1)
    yield port, test_file
    proc.terminate()
    proc.wait(timeout=5)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_host_responds_to_ping(state_dir: Path) -> None:
    proc = _spawn_host()
    try:
        _send(proc, {"jsonrpc": "2.0", "method": "ping", "params": {}, "id": 1})
        resp = _recv(proc)
        assert resp is not None
        assert resp["id"] == 1
        assert resp["result"] == {"pong": True}
    finally:
        proc.stdin.close() if proc.stdin else None  # type: ignore[func-returns-value]
        proc.wait(timeout=5)


def test_host_responds_to_list_empty(state_dir: Path) -> None:
    proc = _spawn_host()
    try:
        _send(proc, {"jsonrpc": "2.0", "method": "download.list", "params": {}, "id": 2})
        resp = _recv(proc)
        assert resp is not None
        assert resp["id"] == 2
        assert resp["result"] == {"downloads": []}
    finally:
        proc.stdin.close() if proc.stdin else None  # type: ignore[func-returns-value]
        proc.wait(timeout=5)


def test_host_runs_download_end_to_end(
    state_dir: Path, server: tuple[int, Path], tmp_path: Path
) -> None:
    port, src = server
    url = f"http://127.0.0.1:{port}/{src.name}"
    proc = _spawn_host()
    try:
        _send(
            proc,
            {
                "jsonrpc": "2.0",
                "method": "download.start",
                "params": {
                    "url": url,
                    "output_dir": str(tmp_path),
                    "filename": src.name,
                },
                "id": 3,
            },
        )
        # First message should be the ack.
        resp = _recv(proc, timeout=10)
        assert resp is not None, "no ack received"
        assert resp["id"] == 3
        download_id = resp["result"]["download_id"]
        assert download_id > 0

        # Then a stream of progress notifications + a final 'complete'.
        seen_complete = False
        deadline = time.time() + 30
        while time.time() < deadline:
            msg = _recv(proc, timeout=2)
            if msg is None:
                continue
            if msg.get("method") == "download.complete":
                seen_complete = True
                assert msg["params"]["download_id"] == download_id
                assert msg["params"]["status"] == "completed"
                break
        assert seen_complete, "did not receive download.complete notification"
    finally:
        proc.stdin.close() if proc.stdin else None  # type: ignore[func-returns-value]
        proc.wait(timeout=5)

    # Verify file landed at the expected path.
    output = tmp_path / src.name
    assert output.exists()
    assert output.stat().st_size == src.stat().st_size
    assert output.read_bytes() == src.read_bytes()
