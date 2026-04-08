"""Local SQLite-backed session storage."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from services.storage_paths import default_session_db_path


@dataclass(frozen=True)
class SessionStoreConfig:
    """Resolved configuration for local session persistence."""

    db_path: str


def get_session_store_config() -> SessionStoreConfig:
    """Load session-store configuration from environment variables."""
    return SessionStoreConfig(
        db_path=os.getenv("SESSION_DB_PATH", "").strip() or default_session_db_path(),
    )


class SessionStore:
    """Minimal interface used by API routes."""

    kind: str = "base"

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def set(self, session_id: str, data: Dict[str, Any]) -> None:
        raise NotImplementedError

    def delete(self, session_id: str) -> None:
        raise NotImplementedError

    def status(self) -> Dict[str, str]:
        return {"backend": self.kind, "status": "unknown"}


class SQLiteSessionStore(SessionStore):
    """Persistent local session store under ./desysflow."""

    kind = "sqlite"

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        self._ensure_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload_json FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if not row:
            return None
        return json.loads(str(row["payload_json"]))

    def set(self, session_id: str, data: Dict[str, Any]) -> None:
        payload_json = json.dumps(data)
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, payload_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id)
                DO UPDATE SET payload_json = excluded.payload_json, updated_at = excluded.updated_at
                """,
                (session_id, payload_json, updated_at),
            )

    def delete(self, session_id: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    def status(self) -> Dict[str, str]:
        return {"backend": self.kind, "status": "ok", "db_path": self._db_path}


_STORE: SessionStore | None = None
_STORE_LOCK = threading.Lock()


def get_session_store() -> SessionStore:
    """Return singleton local session store."""
    global _STORE
    if _STORE is not None:
        return _STORE

    with _STORE_LOCK:
        if _STORE is not None:
            return _STORE
        cfg = get_session_store_config()
        _STORE = SQLiteSessionStore(cfg.db_path)
        return _STORE
