"""SQLite state store for downloads + segments.

Persists every checkpoint (~1s) so resume works after Ctrl-C, SIGKILL, or crash.
Centralised at ~/.yoink/state.db for easy listing via `yoink list`.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from yoink.core.segment import Segment, SegmentStatus

DEFAULT_DB_PATH = Path.home() / ".yoink" / "state.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    final_url TEXT,
    output_path TEXT NOT NULL,
    status TEXT NOT NULL,
    total_size INTEGER,
    downloaded_size INTEGER DEFAULT 0,
    connections INTEGER DEFAULT 8,
    etag TEXT,
    last_modified TEXT,
    headers TEXT,
    cookies TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    error TEXT
);

CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    download_id INTEGER NOT NULL,
    seg_index INTEGER NOT NULL,
    start_byte INTEGER NOT NULL,
    end_byte INTEGER NOT NULL,
    current_byte INTEGER NOT NULL,
    status TEXT NOT NULL,
    retries INTEGER DEFAULT 0,
    last_error TEXT,
    FOREIGN KEY (download_id) REFERENCES downloads(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_segments_download_id ON segments(download_id);
"""


@dataclass
class DownloadRecord:
    """One row in the downloads table."""

    id: int
    url: str
    final_url: str | None
    output_path: str
    status: str
    total_size: int | None
    downloaded_size: int
    connections: int
    etag: str | None
    last_modified: str | None
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    error: str | None = None

    @property
    def output(self) -> Path:
        return Path(self.output_path)

    @property
    def progress_pct(self) -> float:
        if not self.total_size:
            return 0.0
        return self.downloaded_size / self.total_size


class StateStore:
    """Synchronous SQLite wrapper. SQLite writes are sub-ms, safe to call from async.

    Auto-opens connection on init. Also usable as a context manager.
    """

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def __enter__(self) -> StateStore:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None  # type: ignore[assignment]

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("StateStore used outside 'with' block")
        return self._conn

    def create_download(
        self,
        *,
        url: str,
        final_url: str,
        output_path: str,
        status: str,
        total_size: int | None,
        connections: int,
        etag: str | None,
        last_modified: str | None,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
    ) -> int:
        c = self.conn.execute(
            """
            INSERT INTO downloads
              (url, final_url, output_path, status, total_size, connections,
               etag, last_modified, headers, cookies)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                url,
                final_url,
                output_path,
                status,
                total_size,
                connections,
                etag,
                last_modified,
                json.dumps(headers or {}),
                json.dumps(cookies or {}),
            ),
        )
        self.conn.commit()
        assert c.lastrowid is not None
        return int(c.lastrowid)

    def add_segments(self, download_id: int, segments: list[Segment]) -> None:
        self.conn.executemany(
            """
            INSERT INTO segments
              (download_id, seg_index, start_byte, end_byte, current_byte, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    download_id,
                    s.index,
                    s.start_byte,
                    s.end_byte,
                    s.current_byte,
                    s.status.value,
                )
                for s in segments
            ],
        )
        self.conn.commit()

    def checkpoint(
        self,
        download_id: int,
        segments: list[Segment],
        downloaded_size: int,
        status: str,
        error: str | None = None,
    ) -> None:
        """Atomic flush of segment positions + download progress."""
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self.conn:  # transactional
            self.conn.executemany(
                """
                UPDATE segments
                SET current_byte = ?, status = ?
                WHERE download_id = ? AND seg_index = ?
                """,
                [(s.current_byte, s.status.value, download_id, s.index) for s in segments],
            )
            self.conn.execute(
                """
                UPDATE downloads
                SET downloaded_size = ?, status = ?, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (downloaded_size, status, error, now, download_id),
            )

    def get_download(self, download_id: int) -> DownloadRecord | None:
        row = self.conn.execute("SELECT * FROM downloads WHERE id = ?", (download_id,)).fetchone()
        return _row_to_download(row) if row else None

    def list_downloads(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> Iterator[DownloadRecord]:
        if status:
            cur = self.conn.execute(
                """
                SELECT * FROM downloads WHERE status = ?
                ORDER BY id DESC LIMIT ?
                """,
                (status, limit),
            )
        else:
            cur = self.conn.execute("SELECT * FROM downloads ORDER BY id DESC LIMIT ?", (limit,))
        for row in cur:
            yield _row_to_download(row)

    def load_segments(self, download_id: int) -> list[Segment]:
        cur = self.conn.execute(
            """
            SELECT seg_index, start_byte, end_byte, current_byte, status, retries
            FROM segments WHERE download_id = ?
            ORDER BY seg_index
            """,
            (download_id,),
        )
        segments: list[Segment] = []
        for row in cur:
            segments.append(
                Segment(
                    index=row["seg_index"],
                    start_byte=row["start_byte"],
                    end_byte=row["end_byte"],
                    current_byte=row["current_byte"],
                    status=SegmentStatus(row["status"]),
                    retries=row["retries"],
                )
            )
        return segments

    def cancel(self, download_id: int) -> bool:
        """Mark a download as cancelled."""
        cur = self.conn.execute(
            """
            UPDATE downloads
            SET status = 'cancelled', updated_at = ?
            WHERE id = ? AND status IN ('downloading', 'paused', 'failed')
            """,
            (datetime.now(UTC).isoformat(timespec="seconds"), download_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def delete(self, download_id: int) -> bool:
        """Remove download + its segments."""
        cur = self.conn.execute("DELETE FROM downloads WHERE id = ?", (download_id,))
        self.conn.commit()
        return cur.rowcount > 0


def _row_to_download(row: sqlite3.Row) -> DownloadRecord:
    headers_raw = row["headers"] or "{}"
    cookies_raw = row["cookies"] or "{}"
    try:
        headers = json.loads(headers_raw)
    except json.JSONDecodeError:
        headers = {}
    try:
        cookies = json.loads(cookies_raw)
    except json.JSONDecodeError:
        cookies = {}
    return DownloadRecord(
        id=row["id"],
        url=row["url"],
        final_url=row["final_url"],
        output_path=row["output_path"],
        status=row["status"],
        total_size=row["total_size"],
        downloaded_size=row["downloaded_size"],
        connections=row["connections"],
        etag=row["etag"],
        last_modified=row["last_modified"],
        headers=headers,
        cookies=cookies,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        error=row["error"],
    )
