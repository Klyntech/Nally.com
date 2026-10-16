"""Postgres-backed key/value memory for facts."""
from __future__ import annotations

from nally.config import DATABASE_URL
from nally.core.logging import logger

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nally_memory (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL DEFAULT 'default',
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(session_id, key)
);
CREATE INDEX IF NOT EXISTS idx_nally_memory_session ON nally_memory(session_id);
"""


class MemoryStore:
    def __init__(self, database_url: str | None = None):
        self.url = database_url or DATABASE_URL
        if not self.url:
            raise RuntimeError("DATABASE_URL is required")
        self._ensure_schema()

    def _conn(self):
        import psycopg
        return psycopg.connect(self.url)

    def _ensure_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(_SCHEMA)
            conn.commit()
        logger.info("Memory schema ready (postgres)")

    def remember(self, key: str, value: str, session_id: str = "default") -> str:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO nally_memory (session_id, key, value, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (session_id, key)
                DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                """,
                (session_id, key, value),
            )
            conn.commit()
        return f"Remembered: {key}"

    def recall(self, key: str | None = None, session_id: str = "default", limit: int = 20) -> str:
        with self._conn() as conn:
            if key:
                row = conn.execute(
                    "SELECT key, value FROM nally_memory WHERE session_id = %s AND key = %s",
                    (session_id, key),
                ).fetchone()
                if not row:
                    return f"No memory for key: {key}"
                return f"{row[0]}: {row[1]}"
            rows = conn.execute(
                """
                SELECT key, value FROM nally_memory
                WHERE session_id = %s
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (session_id, limit),
            ).fetchall()
        if not rows:
            return "No memories stored."
        return "\n".join(f"- {k}: {v}" for k, v in rows)

    def forget(self, key: str, session_id: str = "default") -> str:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM nally_memory WHERE session_id = %s AND key = %s",
                (session_id, key),
            )
            conn.commit()
            n = cur.rowcount
        return f"Forgot: {key}" if n else f"Nothing to forget for key: {key}"
