"""yt-dlp wrapper: detect video URLs, resolve to direct media URLs.

Always shells out to `python -m yt_dlp` (or `yt-dlp` binary) for stable JSON
output across versions — avoids API drift in the Python library.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MediaFormat:
    """One downloadable format returned by yt-dlp."""

    format_id: str
    ext: str
    resolution: str | None
    fps: float | None
    vcodec: str | None
    acodec: str | None
    filesize: int | None
    tbr: float | None


@dataclass(frozen=True)
class MediaInfo:
    """Metadata about a video page, with format options."""

    title: str
    webpage_url: str
    extractor: str
    duration: float | None
    thumbnail: str | None
    uploader: str | None
    formats: list[MediaFormat] = field(default_factory=list)

    @property
    def best_format(self) -> MediaFormat | None:
        """Best format with both audio + video, else best video, else best overall."""
        if not self.formats:
            return None
        with_av = [f for f in self.formats if f.vcodec != "none" and f.acodec != "none"]
        if with_av:
            return max(with_av, key=lambda f: f.tbr or 0.0)
        video_only = [f for f in self.formats if f.vcodec != "none"]
        if video_only:
            return max(video_only, key=lambda f: f.tbr or 0.0)
        return max(self.formats, key=lambda f: f.tbr or 0.0)


@dataclass(frozen=True)
class ResolvedMedia:
    """Direct URL + suggested filename ready for the download engine."""

    url: str
    filename: str
    ext: str
    format_id: str


class YtDlpNotInstalledError(RuntimeError):
    """Raised when yt-dlp binary / module is unavailable."""


def is_available() -> bool:
    """True if yt-dlp can be invoked via `python -m yt_dlp` or `yt-dlp`."""
    if shutil.which("yt-dlp"):
        return True
    # Probe python -m yt_dlp --version cheaply.
    try:
        proc = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "yt_dlp", "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def probe(url: str) -> MediaInfo:
    """Fetch metadata for a URL without downloading the media."""
    data = _run_ytdlp(
        url,
        extra_args=[
            "--dump-json",
            "--no-warnings",
            "--no-check-certificates",
            "--no-playlist",
        ],
    )
    return _parse_media_info(data)


def resolve(url: str, format_selector: str = "best") -> ResolvedMedia:
    """Resolve a video page URL to a direct media URL + filename."""
    data = _run_ytdlp(
        url,
        extra_args=[
            "--dump-json",
            "--no-warnings",
            "--no-check-certificates",
            "--no-playlist",
            "-f",
            format_selector,
        ],
    )
    return _parse_resolved(data)


async def probe_async(url: str) -> MediaInfo:
    """Async wrapper around probe()."""
    return await asyncio.to_thread(probe, url)


async def resolve_async(url: str, format_selector: str = "best") -> ResolvedMedia:
    """Async wrapper around resolve()."""
    return await asyncio.to_thread(resolve, url, format_selector)


def _run_ytdlp(url: str, extra_args: list[str]) -> dict[str, Any]:
    """Invoke yt-dlp and return parsed JSON of the first result."""
    binary = shutil.which("yt-dlp")
    if binary:
        cmd = [binary, *extra_args, url]
    else:
        cmd = [sys.executable, "-m", "yt_dlp", *extra_args, url]
    return _run_cmd(cmd)


def _run_cmd(cmd: list[str]) -> dict[str, Any]:
    """Run yt-dlp command, return parsed JSON output."""
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except FileNotFoundError as exc:
        raise YtDlpNotInstalledError(
            "yt-dlp is not installed. Install with: pip install 'yoink[media]'"
        ) from exc
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise RuntimeError(f"yt-dlp failed (rc={proc.returncode}): {stderr}")
    if not proc.stdout.strip():
        raise RuntimeError("yt-dlp produced no output")
    first_line = proc.stdout.strip().splitlines()[0]
    parsed: dict[str, Any] = json.loads(first_line)
    return parsed


def _parse_media_info(data: dict[str, Any]) -> MediaInfo:
    raw_formats = data.get("formats") or []
    formats: list[MediaFormat] = []
    for raw in raw_formats:
        if not isinstance(raw, dict):
            continue
        formats.append(
            MediaFormat(
                format_id=str(raw.get("format_id", "")),
                ext=str(raw.get("ext", "mp4")),
                resolution=raw.get("resolution") or raw.get("format_note"),
                fps=raw.get("fps"),
                vcodec=raw.get("vcodec"),
                acodec=raw.get("acodec"),
                filesize=raw.get("filesize") or raw.get("filesize_approx"),
                tbr=raw.get("tbr"),
            )
        )
    return MediaInfo(
        title=str(data.get("title") or data.get("id") or "media"),
        webpage_url=str(data.get("webpage_url") or data.get("original_url") or ""),
        extractor=str(data.get("extractor_key") or data.get("extractor") or "?"),
        duration=data.get("duration"),
        thumbnail=data.get("thumbnail"),
        uploader=data.get("uploader") or data.get("channel"),
        formats=formats,
    )


def _parse_resolved(data: dict[str, Any]) -> ResolvedMedia:
    url = str(data.get("url") or "")
    ext = str(data.get("ext") or "mp4")
    title = str(data.get("title") or "media")
    format_id = str(data.get("format_id") or "?")
    filename = _safe_filename(title, ext)
    return ResolvedMedia(url=url, filename=filename, ext=ext, format_id=format_id)


def _safe_filename(title: str, ext: str) -> str:
    """Sanitise title to a filesystem-safe basename."""
    safe = "".join(c for c in title if c.isalnum() or c in " -_").strip()
    if not safe:
        safe = "media"
    return f"{safe[:120]}.{ext}"


# Re-export so callers can name it without importing Path elsewhere.
__all__ = [
    "MediaFormat",
    "MediaInfo",
    "Path",
    "ResolvedMedia",
    "YtDlpNotInstalledError",
    "is_available",
    "probe",
    "probe_async",
    "resolve",
    "resolve_async",
]
