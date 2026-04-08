"""Conversation persistence with Postgres(Supabase)-first strategy and Redis cache."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from services.storage_paths import default_chat_db_path


@dataclass(frozen=True)
class ConversationStoreConfig:
    backend: str
    db_path: str
    database_url: str
    redis_url: str
    cache_ttl_seconds: int


def get_conversation_store_config() -> ConversationStoreConfig:
    database_url = os.getenv("DATABASE_URL", "").strip()
    backend = os.getenv("CHAT_STORE_BACKEND", "auto").strip().lower()
    db_path = os.getenv("CHAT_DB_PATH", "").strip() or default_chat_db_path()
    return ConversationStoreConfig(
        backend=backend,
        db_path=db_path,
        database_url=database_url,
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        cache_ttl_seconds=int(os.getenv("CHAT_CACHE_TTL_SECONDS", "60")),
    )


class BaseConversationStore:
    def upsert(self, session_id: str, title: str, payload: Dict[str, Any]) -> None:
        raise NotImplementedError

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def list_conversations(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def delete(self, session_id: str) -> bool:
        raise NotImplementedError

    def status(self) -> Dict[str, str]:
        return {"db": "unknown", "cache": "redis", "cache_status": "unknown"}


class ConversationStore(BaseConversationStore):
    """SQLite-backed conversation store with Redis cache."""

    def __init__(self, cfg: ConversationStoreConfig) -> None:
        self._db_path = cfg.db_path
        self._cache_ttl = cfg.cache_ttl_seconds
        self._lock = threading.Lock()
        self._redis = self._init_redis(cfg.redis_url)
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        self._ensure_schema()

    def _init_redis(self, redis_url: str) -> Any | None:
        try:
            import redis

            client = redis.Redis.from_url(redis_url, decode_responses=True)
            client.ping()
            return client
        except Exception:
            return None

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES conversations(session_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);
                """
            )

    def _cache_set_json(self, key: str, value: Any) -> None:
        if self._redis is None:
            return
        try:
            self._redis.set(key, json.dumps(value), ex=self._cache_ttl)
        except Exception:
            pass

    def _cache_get_json(self, key: str) -> Any | None:
        if self._redis is None:
            return None
        try:
            raw = self._redis.get(key)
            if not raw:
                return None
            return json.loads(raw)
        except Exception:
            return None

    def _cache_delete(self, key: str) -> None:
        if self._redis is None:
            return
        try:
            self._redis.delete(key)
        except Exception:
            pass

    def _cache_key_detail(self, session_id: str) -> str:
        return f"desysflow:conversation:detail:{session_id}"

    def _cache_key_list(self) -> str:
        return "desysflow:conversation:list"

    def upsert(self, session_id: str, title: str, payload: Dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload)
        history = payload.get("chat_history", []) if isinstance(payload, dict) else []

        with self._lock, self._conn() as conn:
            exists = conn.execute(
                "SELECT 1 FROM conversations WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if exists:
                conn.execute(
                    """
                    UPDATE conversations
                    SET title = ?, updated_at = ?, payload_json = ?
                    WHERE session_id = ?
                    """,
                    (title, now, payload_json, session_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO conversations (session_id, title, created_at, updated_at, payload_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (session_id, title, now, now, payload_json),
                )

            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            for msg in history:
                if not isinstance(msg, dict):
                    continue
                role = str(msg.get("role", "assistant"))
                content = str(msg.get("content", ""))
                if not content:
                    continue
                conn.execute(
                    """
                    INSERT INTO messages (session_id, role, content, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (session_id, role, content, now),
                )

        detail = self.get(session_id)
        if detail:
            self._cache_set_json(self._cache_key_detail(session_id), detail)
        self._cache_delete(self._cache_key_list())

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        cached = self._cache_get_json(self._cache_key_detail(session_id))
        if cached:
            return cached

        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT session_id, title, created_at, updated_at, payload_json
                FROM conversations
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if not row:
                return None

            payload = json.loads(row["payload_json"])
            messages = conn.execute(
                """
                SELECT role, content, created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()

        detail = {
            "session_id": row["session_id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "chat_history": [
                {"role": m["role"], "content": m["content"], "created_at": m["created_at"]}
                for m in messages
            ],
            "payload": payload,
        }
        self._cache_set_json(self._cache_key_detail(session_id), detail)
        return detail

    def list_conversations(self) -> List[Dict[str, Any]]:
        cached = self._cache_get_json(self._cache_key_list())
        if cached:
            return cached

        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT session_id, title, created_at, updated_at, payload_json
                FROM conversations
                ORDER BY updated_at DESC
                """
            ).fetchall()

        items: List[Dict[str, Any]] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            history = payload.get("chat_history", []) if isinstance(payload, dict) else []
            preview = ""
            for msg in reversed(history):
                if isinstance(msg, dict) and msg.get("role") == "user" and msg.get("content"):
                    preview = str(msg["content"])[:120]
                    break
            items.append(
                {
                    "session_id": row["session_id"],
                    "title": row["title"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "preview": preview,
                }
            )

        self._cache_set_json(self._cache_key_list(), items)
        return items

    def delete(self, session_id: str) -> bool:
        with self._lock, self._conn() as conn:
            cur = conn.execute("DELETE FROM conversations WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            deleted = cur.rowcount > 0

        self._cache_delete(self._cache_key_detail(session_id))
        self._cache_delete(self._cache_key_list())
        return deleted

    def status(self) -> Dict[str, str]:
        cache_status = "ok" if self._redis is not None else "unavailable"
        return {
            "db": "sqlite",
            "db_path": self._db_path,
            "cache": "redis",
            "cache_status": cache_status,
        }


class PostgresConversationStore(BaseConversationStore):
    """Postgres(Supabase-compatible)-backed conversation store with Redis cache."""

    def __init__(self, cfg: ConversationStoreConfig) -> None:
        self._database_url = cfg.database_url
        self._cache_ttl = cfg.cache_ttl_seconds
        self._lock = threading.Lock()
        self._redis = self._init_redis(cfg.redis_url)
        self._ensure_schema()

    def _init_redis(self, redis_url: str) -> Any | None:
        try:
            import redis

            client = redis.Redis.from_url(redis_url, decode_responses=True)
            client.ping()
            return client
        except Exception:
            return None

    def _conn(self):
        import psycopg

        return psycopg.connect(self._database_url)

    def _ensure_schema(self) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS conversations (
                        session_id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        payload_json JSONB NOT NULL
                    );
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS messages (
                        id BIGSERIAL PRIMARY KEY,
                        session_id TEXT NOT NULL REFERENCES conversations(session_id) ON DELETE CASCADE,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);")
            conn.commit()

    def _cache_set_json(self, key: str, value: Any) -> None:
        if self._redis is None:
            return
        try:
            self._redis.set(key, json.dumps(value), ex=self._cache_ttl)
        except Exception:
            pass

    def _cache_get_json(self, key: str) -> Any | None:
        if self._redis is None:
            return None
        try:
            raw = self._redis.get(key)
            if not raw:
                return None
            return json.loads(raw)
        except Exception:
            return None

    def _cache_delete(self, key: str) -> None:
        if self._redis is None:
            return
        try:
            self._redis.delete(key)
        except Exception:
            pass

    def _cache_key_detail(self, session_id: str) -> str:
        return f"desysflow:conversation:detail:{session_id}"

    def _cache_key_list(self) -> str:
        return "desysflow:conversation:list"

    def upsert(self, session_id: str, title: str, payload: Dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        history = payload.get("chat_history", []) if isinstance(payload, dict) else []

        with self._lock, self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO conversations (session_id, title, created_at, updated_at, payload_json)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (session_id)
                    DO UPDATE SET title = EXCLUDED.title, updated_at = EXCLUDED.updated_at, payload_json = EXCLUDED.payload_json
                    """,
                    (session_id, title, now, now, json.dumps(payload)),
                )
                cur.execute("DELETE FROM messages WHERE session_id = %s", (session_id,))
                for msg in history:
                    if not isinstance(msg, dict):
                        continue
                    role = str(msg.get("role", "assistant"))
                    content = str(msg.get("content", ""))
                    if not content:
                        continue
                    cur.execute(
                        """
                        INSERT INTO messages (session_id, role, content, created_at)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (session_id, role, content, now),
                    )
            conn.commit()

        detail = self.get(session_id)
        if detail:
            self._cache_set_json(self._cache_key_detail(session_id), detail)
        self._cache_delete(self._cache_key_list())

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        cached = self._cache_get_json(self._cache_key_detail(session_id))
        if cached:
            return cached

        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT session_id, title, created_at, updated_at, payload_json
                    FROM conversations
                    WHERE session_id = %s
                    """,
                    (session_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                cur.execute(
                    """
                    SELECT role, content, created_at
                    FROM messages
                    WHERE session_id = %s
                    ORDER BY id ASC
                    """,
                    (session_id,),
                )
                messages = cur.fetchall()

        payload = row[4]
        if isinstance(payload, str):
            payload = json.loads(payload)

        detail = {
            "session_id": row[0],
            "title": row[1],
            "created_at": row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2]),
            "updated_at": row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3]),
            "chat_history": [
                {
                    "role": m[0],
                    "content": m[1],
                    "created_at": m[2].isoformat() if hasattr(m[2], "isoformat") else str(m[2]),
                }
                for m in messages
            ],
            "payload": payload if isinstance(payload, dict) else {},
        }
        self._cache_set_json(self._cache_key_detail(session_id), detail)
        return detail

    def list_conversations(self) -> List[Dict[str, Any]]:
        cached = self._cache_get_json(self._cache_key_list())
        if cached:
            return cached

        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT session_id, title, created_at, updated_at, payload_json
                    FROM conversations
                    ORDER BY updated_at DESC
                    """
                )
                rows = cur.fetchall()

        items: List[Dict[str, Any]] = []
        for row in rows:
            payload = row[4]
            if isinstance(payload, str):
                payload = json.loads(payload)
            if not isinstance(payload, dict):
                payload = {}
            history = payload.get("chat_history", []) if isinstance(payload, dict) else []
            preview = ""
            for msg in reversed(history):
                if isinstance(msg, dict) and msg.get("role") == "user" and msg.get("content"):
                    preview = str(msg["content"])[:120]
                    break
            items.append(
                {
                    "session_id": row[0],
                    "title": row[1],
                    "created_at": row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2]),
                    "updated_at": row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3]),
                    "preview": preview,
                }
            )

        self._cache_set_json(self._cache_key_list(), items)
        return items

    def delete(self, session_id: str) -> bool:
        with self._lock, self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM conversations WHERE session_id = %s", (session_id,))
                deleted = (cur.rowcount or 0) > 0
                cur.execute("DELETE FROM messages WHERE session_id = %s", (session_id,))
            conn.commit()

        self._cache_delete(self._cache_key_detail(session_id))
        self._cache_delete(self._cache_key_list())
        return deleted

    def status(self) -> Dict[str, str]:
        cache_status = "ok" if self._redis is not None else "unavailable"
        host = "unknown"
        try:
            parsed = urlparse(self._database_url)
            host = parsed.hostname or "unknown"
        except Exception:
            pass
        return {
            "db": "postgres",
            "db_host": host,
            "cache": "redis",
            "cache_status": cache_status,
        }


_STORE: BaseConversationStore | None = None
_STORE_LOCK = threading.Lock()


def get_conversation_store() -> BaseConversationStore:
    global _STORE
    if _STORE is not None:
        return _STORE

    with _STORE_LOCK:
        if _STORE is not None:
            return _STORE
        cfg = get_conversation_store_config()

        # Postgres-first when URL exists or explicitly requested.
        wants_postgres = cfg.backend in {"auto", "postgres", "supabase"} and bool(cfg.database_url)
        if wants_postgres:
            try:
                _STORE = PostgresConversationStore(cfg)
                return _STORE
            except Exception:
                if cfg.backend in {"postgres", "supabase"}:
                    raise

        _STORE = ConversationStore(cfg)
        return _STORE
