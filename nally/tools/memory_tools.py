"""Memory tools backed by Postgres, scoped to the active agent session."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

from langchain_core.tools import tool

from nally.memory.store import MemoryStore

_store: MemoryStore | None = None
_ACTIVE_SESSION_ID: ContextVar[str] = ContextVar("nally_memory_session_id", default="default")


def _normalize_session_id(session_id: str | None) -> str:
    value = (session_id or "default").strip()
    if not value:
        return "default"
    if len(value) > 200:
        raise ValueError("session_id must be 200 characters or fewer")
    return value


@contextmanager
def memory_session(session_id: str) -> Iterator[None]:
    """Scope memory tool operations to one request's stable session identifier."""
    token: Token[str] = _ACTIVE_SESSION_ID.set(_normalize_session_id(session_id))
    try:
        yield
    finally:
        _ACTIVE_SESSION_ID.reset(token)


def get_memory_store() -> MemoryStore:
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store


@tool
def memory_remember(key: str, value: str) -> str:
    """Store a lasting, non-secret fact about the user or environment. Use short keys like 'name' or 'timezone'."""
    if not key.strip():
        return "Error: memory key cannot be empty"
    if not value.strip():
        return "Error: memory value cannot be empty"
    return get_memory_store().remember(key.strip(), value.strip(), session_id=_ACTIVE_SESSION_ID.get())


@tool
def memory_recall(key: str = "") -> str:
    """Recall a stored fact by key, or list recent memories for the current conversation's user/session."""
    return get_memory_store().recall(
        key.strip() or None,
        session_id=_ACTIVE_SESSION_ID.get(),
    )


@tool
def memory_forget(key: str) -> str:
    """Delete a stored fact by key for the current conversation's user/session."""
    if not key.strip():
        return "Error: memory key cannot be empty"
    return get_memory_store().forget(key.strip(), session_id=_ACTIVE_SESSION_ID.get())
