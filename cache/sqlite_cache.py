"""SQLite cache with per-entry TTLs.

Entries are keyed by (tool, riot_id, params). Expired rows are kept for a
grace period so callers can fall back to stale data when a scrape fails.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    tool       TEXT NOT NULL,
    riot_id    TEXT NOT NULL,
    params     TEXT NOT NULL,
    value      TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    PRIMARY KEY (tool, riot_id, params)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS cache_expires_at ON cache (expires_at);
"""

Key = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class CacheEntry:
    value: Any
    created_at: float
    expires_at: float

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at


def _key(tool: str, riot_id: str, params: Mapping[str, Any] | None) -> Key:
    # Riot IDs are case-insensitive, so fold them to share one entry.
    encoded = json.dumps(dict(params or {}), sort_keys=True, separators=(",", ":"), default=str)
    return tool, riot_id.strip().casefold(), encoded


class SQLiteCache:
    """Async facade over a single SQLite connection.

    Blocking calls run in worker threads. A thread lock serialises access, so
    a cancelled await can never leave two statements racing on the connection.
    Cache failures are logged and treated as misses rather than raised.
    """

    def __init__(self, path: Path | str, stale_grace: float = 7 * 86400) -> None:
        self._path = Path(path)
        self._stale_grace = stale_grace
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    async def get(
        self,
        tool: str,
        riot_id: str = "",
        params: Mapping[str, Any] | None = None,
        *,
        allow_stale: bool = False,
    ) -> CacheEntry | None:
        """Return the entry, or None on a miss. Expired entries need allow_stale."""
        return await asyncio.to_thread(self._get, _key(tool, riot_id, params), allow_stale)

    async def set(
        self,
        tool: str,
        value: Any,
        ttl: float,
        riot_id: str = "",
        params: Mapping[str, Any] | None = None,
    ) -> None:
        """Store a JSON-serialisable value for ttl seconds."""
        await asyncio.to_thread(self._set, _key(tool, riot_id, params), value, ttl)

    async def invalidate(self, *, tool: str | None = None, riot_id: str | None = None) -> int:
        """Delete matching entries (everything when no filter is given)."""
        return await asyncio.to_thread(self._invalidate, tool, riot_id)

    async def purge_expired(self) -> int:
        """Drop entries that expired longer ago than the stale grace period."""
        return await asyncio.to_thread(self._purge)

    async def close(self) -> None:
        await asyncio.to_thread(self._close)

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._path, timeout=10, check_same_thread=False)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.executescript(_SCHEMA)
                conn.commit()
            except sqlite3.Error:
                conn.close()
                raise
            self._conn = conn
        return self._conn

    def _get(self, key: Key, allow_stale: bool) -> CacheEntry | None:
        try:
            with self._lock:
                row = self._connect().execute(
                    "SELECT value, created_at, expires_at FROM cache"
                    " WHERE tool = ? AND riot_id = ? AND params = ?",
                    key,
                ).fetchone()
            if row is None:
                return None
            entry = CacheEntry(json.loads(row[0]), row[1], row[2])
        except (sqlite3.Error, OSError, ValueError) as exc:
            log.warning("cache read failed for %s: %s", key[0], exc)
            return None
        if entry.is_expired and not allow_stale:
            return None
        return entry

    def _set(self, key: Key, value: Any, ttl: float) -> None:
        now = time.time()
        try:
            encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
            with self._lock:
                conn = self._connect()
                with conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO cache VALUES (?, ?, ?, ?, ?, ?)",
                        (*key, encoded, now, now + ttl),
                    )
        except (sqlite3.Error, OSError, TypeError, ValueError) as exc:
            log.warning("cache write failed for %s: %s", key[0], exc)

    def _invalidate(self, tool: str | None, riot_id: str | None) -> int:
        clauses: list[str] = []
        args: list[str] = []
        if tool is not None:
            clauses.append("tool = ?")
            args.append(tool)
        if riot_id is not None:
            clauses.append("riot_id = ?")
            args.append(riot_id.strip().casefold())
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return self._delete(f"DELETE FROM cache{where}", args)

    def _purge(self) -> int:
        cutoff = time.time() - self._stale_grace
        return self._delete("DELETE FROM cache WHERE expires_at < ?", [cutoff])

    def _delete(self, sql: str, args: list[Any]) -> int:
        try:
            with self._lock:
                conn = self._connect()
                with conn:
                    return conn.execute(sql, args).rowcount
        except (sqlite3.Error, OSError) as exc:
            log.warning("cache delete failed: %s", exc)
            return 0

    def _close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
