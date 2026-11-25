"""SQLite response cache (stdlib `sqlite3`, no ORM).

Stores raw response bodies keyed by `SourceRequest.key`, so parsing changes never require
refetching. Each entry carries an integrity hash; corrupt entries are evicted and refetched.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from weather_risk.data.http import SourceRequest

log = logging.getLogger("weather_risk.cache")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS http_cache (
    key             TEXT PRIMARY KEY,
    source_id       TEXT NOT NULL,
    url             TEXT NOT NULL,
    params_json     TEXT NOT NULL,
    fetched_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    dataset_version TEXT,
    body_sha256     TEXT NOT NULL,
    body            BLOB NOT NULL
);
"""


@dataclass(frozen=True)
class CachedBody:
    key: str
    body: bytes
    fetched_at: datetime
    expires_at: datetime
    dataset_version: str | None

    def is_fresh(self, now: datetime) -> bool:
        return now < self.expires_at


def sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


class ResponseCache:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path) if str(path) != ":memory:" else path
        if isinstance(self.path, Path):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # API worker threads share this connection; writes are serialized by SQLite + app lock
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def get(self, req: SourceRequest) -> CachedBody | None:
        """Return the entry (fresh or expired) or None. Corrupt entries are evicted."""
        row = self._conn.execute(
            "SELECT body, body_sha256, fetched_at, expires_at, dataset_version "
            "FROM http_cache WHERE key = ?",
            (req.key,),
        ).fetchone()
        if row is None:
            log.info("cache_miss", extra={"source": req.source_id, "key": req.key[:12]})
            return None
        body, digest, fetched_at, expires_at, version = row
        try:
            if not isinstance(body, bytes) or sha256(body) != digest:
                raise ValueError("body hash mismatch")
            entry = CachedBody(
                key=req.key,
                body=body,
                fetched_at=datetime.fromisoformat(fetched_at),
                expires_at=datetime.fromisoformat(expires_at),
                dataset_version=version,
            )
        except (ValueError, TypeError) as exc:
            log.warning(
                "cache_corrupt_evicted",
                extra={"source": req.source_id, "key": req.key[:12], "error": str(exc)},
            )
            self.delete(req)
            return None
        return entry

    def put(
        self,
        req: SourceRequest,
        body: bytes,
        *,
        ttl_seconds: int,
        dataset_version: str | None = None,
        now: datetime | None = None,
    ) -> CachedBody:
        now = now or datetime.now(UTC)
        expires = now + timedelta(seconds=ttl_seconds)
        self._conn.execute(
            "INSERT OR REPLACE INTO http_cache "
            "(key, source_id, url, params_json, fetched_at, expires_at, dataset_version, "
            "body_sha256, body) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                req.key,
                req.source_id,
                req.url,
                json.dumps(req.params, sort_keys=True),
                now.isoformat(),
                expires.isoformat(),
                dataset_version,
                sha256(body),
                body,
            ),
        )
        self._conn.commit()
        log.info(
            "cache_store",
            extra={"source": req.source_id, "key": req.key[:12], "ttl_s": ttl_seconds},
        )
        return CachedBody(req.key, body, now, expires, dataset_version)

    def delete(self, req: SourceRequest) -> None:
        self._conn.execute("DELETE FROM http_cache WHERE key = ?", (req.key,))
        self._conn.commit()

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM http_cache").fetchone()[0]

    # test helper
    def _corrupt(self, req: SourceRequest) -> None:
        self._conn.execute("UPDATE http_cache SET body = ? WHERE key = ?", (b"garbage", req.key))
        self._conn.commit()
