"""Postgres-backed key/value memory for facts."""
from __future__ import annotations

import re
from typing import TypedDict

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

CREATE TABLE IF NOT EXISTS nally_conversation_turns (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL DEFAULT 'default',
    user_message TEXT NOT NULL,
    assistant_message TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_nally_conversation_session_id
    ON nally_conversation_turns (session_id, id DESC);
"""


class ConversationTurn(TypedDict):
    user: str
    assistant: str


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

    def save_turn(self, user_message: str, assistant_message: str, session_id: str = "default") -> str:
        """Persist one complete user/assistant exchange."""
        user_text = user_message.strip()
        assistant_text = assistant_message.strip()
        if not user_text:
            return "Skipped empty conversation turn."
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO nally_conversation_turns
                    (session_id, user_message, assistant_message)
                VALUES (%s, %s, %s)
                """,
                (session_id, user_text, assistant_text),
            )
            conn.commit()
        return "Conversation turn saved."

    def recall_recent_turns(self, session_id: str = "default", limit: int = 10) -> list[ConversationTurn]:
        """Return the most recent exchanges in chronological order."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT user_message, assistant_message
                FROM nally_conversation_turns
                WHERE session_id = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (session_id, max(1, min(limit, 50))),
            ).fetchall()
        rows.reverse()
        return [{"user": user_text, "assistant": assistant_text} for user_text, assistant_text in rows]

    def search_turns(self, query: str, session_id: str = "default", limit: int = 5) -> list[ConversationTurn]:
        """Find older turns matching meaningful words in the current question."""
        stopwords = {
            "what", "when", "where", "which", "who", "whom", "whose", "why", "how",
            "did", "does", "doing", "say", "said", "tell", "told", "remember", "recall",
            "about", "that", "this", "with", "from", "have", "has", "had", "was", "were",
            "are", "the", "and", "for", "you", "your", "yours", "me", "my", "mine", "our",
            "ours", "is", "it", "in", "on", "at", "to", "of", "do", "i", "we", "they",
            "he", "she", "them", "their", "there", "here",
        }
        terms = [
            term for term in dict.fromkeys(re.findall(r"[A-Za-z0-9]{3,}", query.lower()))
            if term not in stopwords
        ][:6]
        if not terms:
            return []

        conditions = " OR ".join(
            "(user_message ILIKE %s OR assistant_message ILIKE %s)" for _ in terms
        )
        parameters: list[str | int] = [session_id]
        for term in terms:
            pattern = f"%{term}%"
            parameters.extend((pattern, pattern))
        parameters.append(max(1, min(limit, 20)))

        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT user_message, assistant_message
                FROM nally_conversation_turns
                WHERE session_id = %s AND ({conditions})
                ORDER BY id DESC
                LIMIT %s
                """,
                parameters,
            ).fetchall()
        rows.reverse()
        return [{"user": user_text, "assistant": assistant_text} for user_text, assistant_text in rows]
