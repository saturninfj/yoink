"""Segment model: one byte-range piece of a download."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SegmentStatus(StrEnum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


@dataclass
class Segment:
    """A byte-range segment: [start_byte, end_byte] inclusive."""

    index: int
    start_byte: int
    end_byte: int
    current_byte: int | None = None
    status: SegmentStatus = SegmentStatus.PENDING
    retries: int = 0
    last_error: str | None = None

    def __post_init__(self) -> None:
        if self.current_byte is None:
            self.current_byte = self.start_byte

    @property
    def size(self) -> int:
        """Total bytes this segment covers."""
        return self.end_byte - self.start_byte + 1

    @property
    def downloaded(self) -> int:
        """Bytes downloaded so far in this segment."""
        assert self.current_byte is not None
        return self.current_byte - self.start_byte

    @property
    def remaining(self) -> int:
        """Bytes left to download."""
        assert self.current_byte is not None
        return self.end_byte - self.current_byte + 1

    @property
    def progress_pct(self) -> float:
        """Progress 0.0 - 1.0."""
        if self.size == 0:
            return 1.0
        return self.downloaded / self.size

    @property
    def is_complete(self) -> bool:
        return self.status == SegmentStatus.COMPLETED or (
            self.current_byte is not None and self.current_byte > self.end_byte
        )

    def advance(self, n_bytes: int) -> None:
        """Mark n_bytes as downloaded."""
        assert self.current_byte is not None
        self.current_byte += n_bytes
        if self.current_byte > self.end_byte:
            self.status = SegmentStatus.COMPLETED

    def to_pending(self) -> None:
        """Reset to pending (e.g. before retry)."""
        self.status = SegmentStatus.PENDING
        self.last_error = None

    def to_failed(self, err: str) -> None:
        self.status = SegmentStatus.FAILED
        self.last_error = err
        self.retries += 1


def split_into_segments(
    total_size: int,
    n_segments: int,
) -> list[Segment]:
    """Evenly split [0, total_size-1] into n_segments contiguous Segments.

    The last segment absorbs any remainder.
    """
    if total_size <= 0:
        raise ValueError("total_size must be positive")
    if n_segments < 1:
        raise ValueError("n_segments must be >= 1")

    base = total_size // n_segments
    segments: list[Segment] = []
    cursor = 0
    for i in range(n_segments):
        size = base + (total_size - base * n_segments if i == n_segments - 1 else 0)
        start = cursor
        end = cursor + size - 1
        segments.append(Segment(index=i, start_byte=start, end_byte=end))
        cursor = end + 1
    return segments
