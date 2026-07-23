"""JSON-RPC 2.0 protocol types for native messaging."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CookieParam:
    """Cookie as sent by the browser extension."""

    name: str
    value: str
    domain: str | None = None
    path: str | None = "/"


@dataclass
class DownloadStartParams:
    """Parameters for a download.start request."""

    url: str
    filename: str | None = None
    output_dir: str | None = None
    referer: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    cookies: list[CookieParam] = field(default_factory=list)
    connections: int | None = None


@dataclass
class DownloadListParams:
    """Parameters for download.list."""

    status: str | None = None
    limit: int = 50


@dataclass
class DownloadCancelParams:
    """Parameters for download.cancel."""

    download_id: int


@dataclass
class RpcRequest:
    """Incoming JSON-RPC request."""

    method: str
    params: dict[str, Any]
    id: int | str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RpcRequest:
        return cls(
            method=data.get("method", ""),
            params=data.get("params") or {},
            id=data.get("id"),
        )


@dataclass
class RpcResponse:
    """JSON-RPC response."""

    id: int | str | None
    result: Any = None
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"jsonrpc": "2.0", "id": self.id}
        if self.error is not None:
            out["error"] = self.error
        else:
            out["result"] = self.result
        return out


@dataclass
class RpcNotification:
    """JSON-RPC notification (no id, server-initiated)."""

    method: str
    params: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "method": self.method,
            "params": self.params,
        }


# Error codes (JSON-RPC 2.0 + our extensions).
ERR_INVALID_REQUEST = -32600
ERR_METHOD_NOT_FOUND = -32601
ERR_INVALID_PARAMS = -32602
ERR_INTERNAL = -32603
ERR_DOWNLOAD_FAILED = -32000


def make_error(code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return err


def params_to_download_start(params: dict[str, Any]) -> DownloadStartParams:
    """Build DownloadStartParams from raw dict (cookies converted to CookieParam)."""
    raw_cookies = params.get("cookies") or []
    cookies = [
        CookieParam(
            name=str(c.get("name", "")),
            value=str(c.get("value", "")),
            domain=c.get("domain"),
            path=c.get("path", "/"),
        )
        for c in raw_cookies
        if isinstance(c, dict)
    ]
    return DownloadStartParams(
        url=str(params.get("url", "")),
        filename=params.get("filename"),
        output_dir=params.get("output_dir"),
        referer=params.get("referer"),
        headers={k: str(v) for k, v in (params.get("headers") or {}).items()},
        cookies=cookies,
        connections=params.get("connections"),
    )


def cookies_to_header_value(cookies: list[CookieParam]) -> str:
    """Build a Cookie header value from a list of cookies."""
    if not cookies:
        return ""
    return "; ".join(f"{c.name}={c.value}" for c in cookies)


def dictify(obj: object) -> Any:
    """Convert dataclass / list / dict to JSON-serialisable dict."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, list):
        return [dictify(x) for x in obj]
    if isinstance(obj, dict):
        return {k: dictify(v) for k, v in obj.items()}
    return obj
