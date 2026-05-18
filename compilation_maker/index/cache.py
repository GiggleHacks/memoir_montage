"""SQLite cache of per-file analysis results.

Schema is keyed on absolute path; (size, mtime) form the freshness check.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from ..paths import cache_db_path


SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path             TEXT PRIMARY KEY,
    size             INTEGER NOT NULL,
    mtime            REAL NOT NULL,
    duration         REAL,
    has_audio        INTEGER,
    width            INTEGER,
    height           INTEGER,
    created_year     INTEGER,
    indexed_at       REAL NOT NULL,
    nsfw_peak        REAL,
    nsfw_soft_count  INTEGER,
    face_max_count   INTEGER,
    motion_score     REAL,
    speech_fraction  REAL,
    error            TEXT
);
CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);
"""


_lock = threading.Lock()


class Cache:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or cache_db_path()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        with _lock:
            self._conn.executescript(SCHEMA)

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        with _lock:
            cur = self._conn.cursor()
            try:
                yield cur
            finally:
                cur.close()

    def close(self) -> None:
        with _lock:
            self._conn.close()

    def get_fresh(self, path: str, size: int, mtime: float) -> sqlite3.Row | None:
        with self._cursor() as c:
            r = c.execute(
                "SELECT * FROM files WHERE path = ? AND size = ? AND ABS(mtime - ?) < 1.0",
                (path, size, mtime),
            ).fetchone()
            return r

    def upsert(self, row: dict) -> None:
        row = dict(row)
        row.setdefault("indexed_at", time.time())
        cols = [
            "path", "size", "mtime", "duration", "has_audio", "width", "height",
            "created_year", "indexed_at", "nsfw_peak", "nsfw_soft_count",
            "face_max_count", "motion_score", "speech_fraction", "error",
        ]
        values = [row.get(c) for c in cols]
        placeholders = ",".join("?" for _ in cols)
        sets = ",".join(f"{c}=excluded.{c}" for c in cols if c != "path")
        with self._cursor() as c:
            c.execute(
                f"INSERT INTO files ({','.join(cols)}) VALUES ({placeholders}) "
                f"ON CONFLICT(path) DO UPDATE SET {sets}",
                values,
            )

    def delete_missing(self, present_paths: set[str]) -> int:
        with self._cursor() as c:
            existing = {r["path"] for r in c.execute("SELECT path FROM files")}
            stale = existing - present_paths
            for p in stale:
                c.execute("DELETE FROM files WHERE path = ?", (p,))
            return len(stale)

    def all_under(self, root: str) -> list[sqlite3.Row]:
        root = str(Path(root).resolve())
        with self._cursor() as c:
            return list(c.execute(
                "SELECT * FROM files WHERE path LIKE ? ESCAPE '\\'",
                (root.replace("\\", "\\\\").replace("%", "\\%") + "%",),
            ))

    def all(self) -> list[sqlite3.Row]:
        with self._cursor() as c:
            return list(c.execute("SELECT * FROM files"))

    def aggregate(
        self,
        root: str,
        *,
        nsfw_strict: float,
        nsfw_soft_min: int,
        speech_min: float,
        motion_min: float,
        min_duration: float,
    ) -> dict:
        """Compute roll-up stats from cache rows under root using current thresholds."""
        rows = self.all_under(root)
        total = len(rows)
        ok = sum(1 for r in rows if not r["error"])
        nsfw = sum(
            1 for r in rows
            if not r["error"]
            and ((r["nsfw_peak"] or 0.0) >= nsfw_strict
                 or (r["nsfw_soft_count"] or 0) >= nsfw_soft_min)
        )
        face = sum(1 for r in rows if not r["error"] and (r["face_max_count"] or 0) >= 1)
        talking = sum(1 for r in rows if not r["error"] and (r["speech_fraction"] or 0.0) >= speech_min)
        motion = sum(1 for r in rows if not r["error"] and (r["motion_score"] or 0.0) >= motion_min)
        long_enough = sum(1 for r in rows if not r["error"] and (r["duration"] or 0.0) >= min_duration)
        total_duration = sum(float(r["duration"] or 0.0) for r in rows if not r["error"])
        total_size = sum(int(r["size"] or 0) for r in rows)
        failed = sum(1 for r in rows if r["error"])
        eligible = sum(
            1 for r in rows
            if not r["error"]
            and (r["duration"] or 0.0) >= min_duration
            and not ((r["nsfw_peak"] or 0.0) >= nsfw_strict
                     or (r["nsfw_soft_count"] or 0) >= nsfw_soft_min)
            and (r["face_max_count"] or 0) >= 1
            and (r["speech_fraction"] or 0.0) >= speech_min
            and (r["motion_score"] or 0.0) >= motion_min
        )
        return {
            "total": total,
            "ok": ok,
            "failed": failed,
            "nsfw": nsfw,
            "face": face,
            "talking": talking,
            "motion": motion,
            "long_enough": long_enough,
            "eligible": eligible,
            "total_duration_seconds": total_duration,
            "total_size_bytes": total_size,
        }
