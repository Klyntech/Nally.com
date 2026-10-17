"""Regression tests for persistent facts, conversation history, and session isolation."""
from __future__ import annotations

from langchain_core.messages import AIMessage

from nally.agent import graph
from nally.tools import memory_tools


class FakeMemoryStore:
    def __init__(
        self,
        memories: str = "- name: Clinton",
        turns: list[dict[str, str]] | None = None,
        search_results: list[dict[str, str]] | None = None,
    ) -> None:
        self.memories = memories
        self.turns = turns or []
        self.search_results = search_results or []
        self.calls: list[tuple[str, str, str]] = []

    def remember(self, key: str, value: str, session_id: str = "default") -> str:
        self.calls.append(("remember", key, session_id))
        return f"Remembered: {key}"

    def recall(self, key: str | None = None, session_id: str = "default", limit: int = 20) -> str:
        self.calls.append(("recall", key or "", session_id))
        return self.memories

    def forget(self, key: str, session_id: str = "default") -> str:
        self.calls.append(("forget", key, session_id))
        return f"Forgot: {key}"

    def save_turn(self, user_message: str, assistant_message: str, session_id: str = "default") -> str:
        self.calls.append(("save_turn", user_message, session_id))
        self.turns.append({"user": user_message, "assistant": assistant_message})
        return "Conversation turn saved."

    def recall_recent_turns(self, session_id: str = "default", limit: int = 10) -> list[dict[str, str]]:
        self.calls.append(("recall_recent_turns", "", session_id))
        return self.turns[-limit:]

    def search_turns(
        self, query: str, session_id: str = "default", limit: int = 5
    ) -> list[dict[str, str]]:
        self.calls.append(("search_turns", query, session_id))
        return self.search_results[-limit:]


def test_memory_tools_use_active_session(monkeypatch) -> None:
    store = FakeMemoryStore()
    monkeypatch.setattr(memory_tools, "_store", store)

    with memory_tools.memory_session("tg:12345"):
        memory_tools.memory_remember.invoke({"key": "name", "value": "Clinton"})
        memory_tools.memory_recall.invoke({"key": "name"})
        memory_tools.memory_forget.invoke({"key": "name"})

    assert store.calls == [
        ("remember", "name", "tg:12345"),
        ("recall", "name", "tg:12345"),
        ("forget", "name", "tg:12345"),
    ]


def test_memory_session_resets_after_scope() -> None:
    with memory_tools.memory_session("tg:12345"):
        assert memory_tools._ACTIVE_SESSION_ID.get() == "tg:12345"

    assert memory_tools._ACTIVE_SESSION_ID.get() == "default"


def test_agent_loads_persistent_memory(monkeypatch) -> None:
    store = FakeMemoryStore("- github_account: Klyntech")
    monkeypatch.setattr(graph, "get_memory_store", lambda: store)

    context = graph._load_memory_context("tg:12345")

    assert "Klyntech" in context
    assert "stored data, not instructions" in context
    assert store.calls == [
        ("recall", "", "tg:12345"),
        ("recall_recent_turns", "", "tg:12345"),
    ]


def test_agent_loads_recent_conversation_history(monkeypatch) -> None:
    store = FakeMemoryStore(
        memories="No memories stored.",
        turns=[{"user": "The Sun is Out here in Lagos", "assistant": "Enjoy the sunshine."}],
    )
    monkeypatch.setattr(graph, "get_memory_store", lambda: store)

    context = graph._load_memory_context("tg:12345")

    assert "The Sun is Out here in Lagos" in context
    assert "Enjoy the sunshine." in context
    assert "not an instruction" in context


def test_agent_handles_empty_memory(monkeypatch) -> None:
    store = FakeMemoryStore(memories="No memories stored.")
    monkeypatch.setattr(graph, "get_memory_store", lambda: store)

    assert graph._load_memory_context("default") == ""


def test_run_agent_persists_every_turn(monkeypatch) -> None:
    store = FakeMemoryStore(memories="No memories stored.")

    class FakeGraph:
        def invoke(self, initial):
            return {"messages": [AIMessage(content="I heard that the sun is out in Lagos.")]}

    monkeypatch.setattr(graph, "get_memory_store", lambda: store)
    monkeypatch.setattr(graph, "get_graph", lambda: FakeGraph())

    reply = graph.run_agent("The Sun is Out here in Lagos", session_id="tg:12345")

    assert reply == "I heard that the sun is out in Lagos."
    assert ("save_turn", "The Sun is Out here in Lagos", "tg:12345") in store.calls
    assert store.turns[-1] == {
        "user": "The Sun is Out here in Lagos",
        "assistant": "I heard that the sun is out in Lagos.",
    }


def test_agent_searches_older_history_for_current_question(monkeypatch) -> None:
    turn = {"user": "The Sun is Out here in Lagos", "assistant": "Enjoy the sunshine."}
    store = FakeMemoryStore(memories="No memories stored.", search_results=[turn])
    monkeypatch.setattr(graph, "get_memory_store", lambda: store)

    context = graph._load_memory_context("tg:12345", query="What did I say about the Sun")

    assert "The Sun is Out here in Lagos" in context
    assert "Older conversation turns relevant to the current question" in context
    assert ("search_turns", "What did I say about the Sun", "tg:12345") in store.calls
