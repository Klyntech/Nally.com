"""Agent recovery tests for failures during multi-step tool use."""
from __future__ import annotations

import time
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from nally.agent import graph


def _response(*, content: str | None = None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_agent_continues_after_tool_failure(monkeypatch) -> None:
    @tool
    def unstable_tool(query: str) -> str:
        """A test tool that fails once when invoked."""
        raise RuntimeError("simulated downstream failure")

    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name="unstable_tool",
            arguments='{"query":"continue the task"}',
        ),
    )
    responses = [
        _response(tool_calls=[tool_call]),
        _response(content="I recovered and completed the task."),
    ]
    calls = []

    def fake_completion(messages, tools=None, model=None, timeout=None):
        calls.append(messages)
        return responses.pop(0)

    monkeypatch.setattr(graph, "chat_completion", fake_completion)
    monkeypatch.setattr(graph, "get_tools", lambda: [unstable_tool])
    monkeypatch.setattr(graph, "get_tools_by_name", lambda: {"unstable_tool": unstable_tool})

    initial = {
        "messages": [
            SystemMessage(content="Test system prompt"),
            HumanMessage(content="Complete a multi-step task"),
        ],
        "iteration": 0,
        "tool_calls": 0,
        "started_at": time.time(),
        "stop_reason": "",
        "session_id": "test-session",
    }

    final = graph.build_graph().invoke(initial)
    messages = final["messages"]

    assert len(calls) == 2
    assert any(
        isinstance(message, ToolMessage)
        and "simulated downstream failure" in str(message.content)
        for message in messages
    )
    assert isinstance(messages[-1], AIMessage)
    assert messages[-1].content == "I recovered and completed the task."
