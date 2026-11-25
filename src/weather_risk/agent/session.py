"""SQLite-backed conversation storage (stdlib sqlite3).

Each session stores its turns (user message + full ChatResponse JSON). The agent receives a
bounded history (last N turns) and the latest resolved context (hubs, hazards, metric, period).
Sessions are isolated by an unguessable server-generated id.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS turns (
    session_id   TEXT NOT NULL REFERENCES sessions(session_id),
    turn         INTEGER NOT NULL,
    created_at   TEXT NOT NULL,
    user_message TEXT NOT NULL,
    response     TEXT NOT NULL,
    PRIMARY KEY (session_id, turn)
);
"""


class SessionNotFoundError(LookupError):
    pass


class SessionStore:
    def __init__(self, path: Path | str, *, max_turns_per_session: int = 50) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()
        self.max_turns = max_turns_per_session

    def create(self) -> str:
        sid = secrets.token_urlsafe(16)
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute("INSERT INTO sessions VALUES (?, ?, ?)", (sid, now, now))
            self._conn.commit()
        return sid

    def exists(self, sid: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM sessions WHERE session_id = ?", (sid,)).fetchone()
        return row is not None

    def next_turn(self, sid: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(turn), 0) FROM turns WHERE session_id = ?", (sid,)
        ).fetchone()
        return int(row[0]) + 1

    def append(self, sid: str, turn: int, user_message: str, response: dict[str, Any]) -> None:
        if not self.exists(sid):
            raise SessionNotFoundError(sid)
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT INTO turns VALUES (?, ?, ?, ?, ?)",
                (sid, turn, now, user_message, json.dumps(response, default=str)),
            )
            self._conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?", (now, sid)
            )
            self._conn.commit()

    def history(self, sid: str, limit: int) -> list[dict[str, Any]]:
        if not self.exists(sid):
            raise SessionNotFoundError(sid)
        rows = self._conn.execute(
            "SELECT turn, user_message, response, created_at FROM turns WHERE session_id = ? "
            "ORDER BY turn DESC LIMIT ?",
            (sid, limit),
        ).fetchall()
        return [
            {"turn": t, "user_message": u, "response": json.loads(r), "created_at": c}
            for t, u, r, c in reversed(rows)
        ]

    def turn_count(self, sid: str) -> int:
        return self.next_turn(sid) - 1
