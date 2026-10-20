"""Regression tests for wall-time budget enforcement and partial results."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from nally.agent import graph as agent_graph
from nally.agent.graph import (
    _over_budget,
    _partial_stop_message,
    _remaining_wall_time,
    llm_node,
    tools_node,
)
from nally.config import MAX_WALL_TIME


def _base_state(**overrides):
    state = {
        "messages": [
            SystemMessage(content="sys"),
            HumanMessage(content="Research something complex"),
        ],
        "iteration": 0,
        "tool_calls": 0,
        "started_at": time.time(),
        "stop_reason": "",
        "session_id": "test-session",
    }
    state.update(overrides)
    return state


def test_remaining_wall_time_decreases():
    state = _base_state(started_at=time.time() - 30)
    remaining = _remaining_wall_time(state)
    assert 55 <= remaining <= 65  # ~60 left given default 90


def test_over_budget_wall_time():
    state = _base_state(started_at=time.time() - (MAX_WALL_TIME + 5))
    assert _over_budget(state) == f"max_wall_time={MAX_WALL_TIME}s"


def test_partial_stop_message_prefers_useful_content():
    state = _base_state(
        messages=[
            SystemMessage(content="sys"),
            HumanMessage(content="q"),
            AIMessage(content="Here is a substantial intermediate finding about CAPTA and hotlines."),
            AIMessage(content="Let me fetch a couple of key sources"),
        ]
    )
    msg = _partial_stop_message(state, "max_wall_time=90s")
    assert "could not fully complete" in msg
    assert "CAPTA" in msg
    assert "Let me fetch" not in msg


def test_partial_stop_message_when_only_status():
    state = _base_state(
        messages=[
            HumanMessage(content="q"),
            AIMessage(content="Let me fetch sources"),
        ]
    )
    msg = _partial_stop_message(state, "max_wall_time=90s")
    assert "could not complete" in msg
    assert "narrower question" in msg


def test_llm_node_passes_remaining_timeout_and_stops_on_exhausted_budget():
    state = _base_state(started_at=time.time() - (MAX_WALL_TIME + 1))
    out = llm_node(state)
    assert out.get("stop_reason")
    assert "could not" in out["messages"][0].content.lower()


def test_llm_node_propagates_timeout_to_chat_completion():
    state = _base_state(started_at=time.time() - 10)  # ~80s remaining
    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock(message=MagicMock(content="ok", tool_calls=None))]

    with patch.object(agent_graph, "chat_completion", return_value=fake_resp) as mock_cc:
        with patch.object(agent_graph, "get_tools", return_value=[]):
            out = llm_node(state)

    assert out["iteration"] == 1
    assert mock_cc.called
    kwargs = mock_cc.call_args.kwargs
    assert "timeout" in kwargs
    # Should be roughly remaining - 1s safety margin
    assert 70 <= kwargs["timeout"] <= 85


def test_tools_node_stops_when_budget_exhausted_mid_loop():
    state = _base_state(
        started_at=time.time() - (MAX_WALL_TIME - 0.1),
        messages=[
            HumanMessage(content="q"),
            AIMessage(
                content="",
                tool_calls=[{"id": "c1", "name": "web_search", "args": {"query": "x"}}],
            ),
        ],
    )
    # Force remaining <= 0.5 by advancing started_at slightly more inside if needed
    state["started_at"] = time.time() - MAX_WALL_TIME
    out = tools_node(state)
    assert out.get("stop_reason")
    contents = " ".join(
        m.content for m in out["messages"] if hasattr(m, "content") and m.content
    )
    assert "budget" in contents.lower() or "could not" in contents.lower()
