"""Memory tools backed by Postgres."""
from __future__ import annotations

from langchain_core.tools import tool

from nally.memory.store import MemoryStore

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store


@tool
def memory_remember(key: str, value: str) -> str:
    """Store a lasting fact about the user or environment. Use short keys like 'name', 'timezone'."""
    return _get_store().remember(key, value)


@tool
def memory_recall(key: str = "") -> str:
    """Recall a stored fact by key, or list recent memories if key is empty."""
    return _get_store().recall(key or None)


@tool
def memory_forget(key: str) -> str:
    """Delete a stored fact by key."""
    return _get_store().forget(key)
