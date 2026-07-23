"""Native messaging host: stdio JSON-RPC daemon for browser integration.

Speaks Chrome's native messaging protocol:
  - 4-byte little-endian length prefix
  - UTF-8 JSON payload
  - chrome.runtime.connectNative opens a persistent session
"""

from __future__ import annotations

import asyncio
import json
import struct
import sys
from pathlib import Path
from typing import Any

from yoink.browser.protocol import (
    ERR_DOWNLOAD_FAILED,
    ERR_INVALID_PARAMS,
    ERR_METHOD_NOT_FOUND,
    RpcNotification,
    RpcRequest,
    RpcResponse,
    cookies_to_header_value,
    dictify,
    make_error,
    params_to_download_start,
)
from yoink.core.engine import DownloadEngine
from yoink.core.http_client import ResponseInfo
from yoink.core.segment import Segment
from yoink.core.state import StateStore

DEFAULT_OUTPUT_DIR = Path.home() / "Downloads"
NATIVE_MSG_LEN_BYTES = 4


def _read_native_message_sync() -> dict[str, Any] | None:
    """Read one Chrome native message from stdin. None on EOF."""
    raw_len = sys.stdin.buffer.read(NATIVE_MSG_LEN_BYTES)
    if len(raw_len) < NATIVE_MSG_LEN_BYTES:
        return None
    msg_len = struct.unpack("<I", raw_len)[0]
    if msg_len == 0:
        return None
    data = sys.stdin.buffer.read(msg_len)
    if len(data) < msg_len:
        return None
    try:
        result: dict[str, Any] = json.loads(data.decode("utf-8"))
        return result
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _write_native_message_sync(msg: dict[str, Any]) -> None:
    """Write one Chrome native message to stdout."""
    payload = json.dumps(msg).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(payload)))
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


class NativeHost:
    """Bridges extension requests to DownloadEngine + emits progress events."""

    def __init__(self) -> None:
        self._state = StateStore()
        self._downloads: dict[int, asyncio.Task[None]] = {}
        self._write_lock = asyncio.Lock()

    async def run(self) -> None:
        """Main loop: read requests, dispatch, send responses/notifications."""
        try:
            while True:
                msg = await asyncio.to_thread(_read_native_message_sync)
                if msg is None:
                    break
                await self._handle_message(msg)
        finally:
            for task in self._downloads.values():
                task.cancel()
            self._state.close()

    async def _handle_message(self, raw: dict[str, Any]) -> None:
        req = RpcRequest.from_dict(raw)
        if req.method == "ping":
            await self._respond(req.id, {"pong": True})
            return
        if req.method == "download.start":
            await self._handle_download_start(req)
            return
        if req.method == "download.cancel":
            await self._handle_download_cancel(req)
            return
        if req.method == "download.list":
            await self._handle_download_list(req)
            return
        await self._respond(
            req.id,
            error=make_error(ERR_METHOD_NOT_FOUND, f"unknown method: {req.method}"),
        )

    async def _handle_download_start(self, req: RpcRequest) -> None:
        """Pre-register download synchronously, then stream in background."""
        try:
            params = params_to_download_start(req.params)
        except (KeyError, ValueError, TypeError) as exc:
            await self._respond(
                req.id,
                error=make_error(ERR_INVALID_PARAMS, f"bad params: {exc}"),
            )
            return

        output_dir = Path(params.output_dir) if params.output_dir else DEFAULT_OUTPUT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = params.filename or "yoink-download.bin"
        output = (output_dir / filename).resolve()

        # Build per-request headers.
        headers = dict(params.headers)
        if params.referer:
            headers.setdefault("Referer", params.referer)
        if params.cookies:
            cookie_header = cookies_to_header_value(params.cookies)
            if cookie_header:
                headers["Cookie"] = cookie_header

        engine = DownloadEngine(
            connections=params.connections or 8,
            state_store=self._state,
            extra_headers=headers,
        )

        # Probe + pre-register synchronously so we can return the id immediately.
        try:
            download_id, segments, info = await engine.prepare(params.url, output)
        except Exception as exc:  # noqa: BLE001
            await self._respond(
                req.id,
                error=make_error(ERR_DOWNLOAD_FAILED, f"probe failed: {exc}"),
            )
            return

        # If server doesn't support ranges, prepare returns -1; we still spawn
        # and let engine fall back to single-segment. Progress will use the
        # fresh id created by stream().
        task = asyncio.create_task(
            self._run_download(
                engine=engine,
                url=params.url,
                output=output,
                info=info,
                download_id=download_id,
                segments=segments,
            )
        )
        if download_id > 0:
            self._downloads[download_id] = task

        await self._respond(
            req.id,
            {
                "download_id": download_id,
                "output": str(output),
                "total": info.total_size,
            },
        )

    async def _run_download(
        self,
        *,
        engine: DownloadEngine,
        url: str,
        output: Path,
        info: ResponseInfo,
        download_id: int,
        segments: list[Segment],
    ) -> None:
        """Background task: stream bytes + emit progress/complete notifications."""
        try:
            async for tick in engine.stream(
                url,
                output,
                download_id=download_id if download_id > 0 else None,
                segments=segments or None,
                info=info,
            ):
                # If prepare() returned -1 (no pre-registration), stream() created
                # a new record. Look up the latest id lazily.
                live_id = download_id
                if live_id <= 0:
                    record = next(iter(self._state.list_downloads(limit=1)), None)
                    live_id = record.id if record else -1
                await self._notify(
                    "download.progress",
                    {
                        "download_id": live_id,
                        "downloaded": tick.downloaded,
                        "total": tick.total or info.total_size,
                        "speed_bps": tick.speed_bps,
                    },
                )
            live_id = download_id
            if live_id <= 0:
                record = next(iter(self._state.list_downloads(limit=1)), None)
                live_id = record.id if record else -1
            await self._notify(
                "download.complete",
                {"download_id": live_id, "status": "completed"},
            )
        except asyncio.CancelledError:
            await self._notify(
                "download.complete",
                {"download_id": download_id, "status": "cancelled"},
            )
            raise
        except Exception as exc:  # noqa: BLE001
            await self._notify(
                "download.complete",
                {
                    "download_id": download_id,
                    "status": "failed",
                    "error": str(exc),
                },
            )

    async def _handle_download_cancel(self, req: RpcRequest) -> None:
        raw_id = req.params.get("download_id")
        if raw_id is None:
            await self._respond(
                req.id,
                error=make_error(ERR_INVALID_PARAMS, "download_id required"),
            )
            return
        try:
            download_id = int(raw_id)
        except (TypeError, ValueError):
            await self._respond(
                req.id,
                error=make_error(ERR_INVALID_PARAMS, "download_id must be int"),
            )
            return

        task = self._downloads.pop(download_id, None)
        if task:
            task.cancel()
        ok = self._state.cancel(download_id)
        await self._respond(req.id, {"cancelled": ok})

    async def _handle_download_list(self, req: RpcRequest) -> None:
        status = req.params.get("status")
        limit = int(req.params.get("limit", 50))
        records = list(self._state.list_downloads(status=status, limit=limit))
        await self._respond(req.id, {"downloads": [dictify(r) for r in records]})

    async def _respond(
        self,
        msg_id: int | str | None,
        result: Any = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        response = RpcResponse(id=msg_id, result=result, error=error)
        await self._send(response.to_dict())

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        notif = RpcNotification(method=method, params=params)
        await self._send(notif.to_dict())

    async def _send(self, msg: dict[str, Any]) -> None:
        async with self._write_lock:
            try:
                await asyncio.to_thread(_write_native_message_sync, msg)
            except (BrokenPipeError, OSError):
                raise KeyboardInterrupt from None


def main() -> None:
    """Entry point for `yoink daemon` / `python -m yoink.browser.native_host`."""
    host = NativeHost()
    try:
        asyncio.run(host.run())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
