"""Regression tests for wall-time budget enforcement and partial results."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

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


def test_llm_node_skips_call_when_budget_under_half_second():
    state = _base_state(started_at=time.time() - (MAX_WALL_TIME - 0.2))
    with patch.object(agent_graph, "chat_completion") as mock_cc:
        out = llm_node(state)
    mock_cc.assert_not_called()
    assert out.get("stop_reason")
    assert "could not" in out["messages"][0].content.lower()


def test_chat_completion_shares_deadline_across_provider_fallbacks():
    """Later providers must not re-spend the full original timeout."""
    from nally.agent import llm as llm_mod

    call_timeouts: list[float] = []

    def fail_openrouter(*args, **kwargs):
        call_timeouts.append(float(kwargs.get("timeout") or 0))
        time.sleep(0.15)
        raise RuntimeError("OpenRouter down")

    def fail_nim(*args, **kwargs):
        call_timeouts.append(float(kwargs.get("timeout") or 0))
        raise RuntimeError("NIM down")

    def fail_zen(*args, **kwargs):
        call_timeouts.append(float(kwargs.get("timeout") or 0))
        raise RuntimeError("Zen down")

    with (
        patch.object(llm_mod, "MODEL", "primary"),
        patch.object(llm_mod, "FALLBACK_MODELS", []),
        patch.object(llm_mod, "_openrouter_client", return_value=object()),
        patch.object(llm_mod, "_call_openrouter", side_effect=fail_openrouter),
        patch.object(llm_mod, "NVIDIA_NIM_API_KEY", "nim"),
        patch.object(llm_mod, "_call_nvidia_nim", side_effect=fail_nim),
        patch.object(llm_mod, "OPENCODE_API_KEY", "zen"),
        patch.object(llm_mod, "OPENCODE_MODEL", "zen-m"),
        patch.object(llm_mod, "OPENCODE_FALLBACK_MODELS", []),
        patch.object(llm_mod, "_call_opencode_zen", side_effect=fail_zen),
    ):
        try:
            llm_mod.chat_completion(
                [{"role": "user", "content": "hi"}],
                timeout=0.4,
            )
        except Exception:
            pass

    assert len(call_timeouts) >= 1
    # First attempt may get up to ~0.4s; later attempts must be strictly less
    # than the original budget (shared deadline consumes time).
    assert call_timeouts[0] <= 0.4 + 0.05
    if len(call_timeouts) > 1:
        assert call_timeouts[1] < call_timeouts[0] + 0.01


def test_tools_node_times_out_slow_tool():
    from langchain_core.tools import tool

    @tool
    def slow_tool(query: str) -> str:
        """Intentionally slow tool for timeout test."""
        time.sleep(5)
        return "done"

    state = _base_state(
        started_at=time.time() - (MAX_WALL_TIME - 1.0),  # ~1s left
        messages=[
            HumanMessage(content="q"),
            AIMessage(
                content="",
                tool_calls=[{"id": "c1", "name": "slow_tool", "args": {"query": "x"}}],
            ),
        ],
    )
    with (
        patch.object(agent_graph, "get_tools_by_name", return_value={"slow_tool": slow_tool}),
    ):
        out = tools_node(state)

    tool_msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert tool_msgs
    assert "exceeded remaining time budget" in str(tool_msgs[0].content).lower() or "budget" in str(
        tool_msgs[0].content
    ).lower()


def test_tools_node_returns_within_budget_even_if_worker_still_blocked():
    """Caller must not wait for a timed-out tool thread to finish.

    ThreadPoolExecutor as a context manager would call shutdown(wait=True) and
    re-block the agent; this test fails if that regression returns.
    """
    from langchain_core.tools import tool

    block_seconds = 4.0

    @tool
    def blocked_tool(query: str) -> str:
        """Blocks longer than the allowed tool budget."""
        time.sleep(block_seconds)
        return "should-not-be-returned"

    # Leave ~0.8s of wall budget so tool_timeout is under 1s.
    state = _base_state(
        started_at=time.time() - (MAX_WALL_TIME - 0.8),
        messages=[
            HumanMessage(content="q"),
            AIMessage(
                content="",
                tool_calls=[{"id": "c1", "name": "blocked_tool", "args": {"query": "x"}}],
            ),
        ],
    )
    t0 = time.monotonic()
    with patch.object(
        agent_graph, "get_tools_by_name", return_value={"blocked_tool": blocked_tool}
    ):
        out = tools_node(state)
    elapsed = time.monotonic() - t0

    # Must return well before the blocked worker finishes.
    assert elapsed < 2.0, f"tools_node blocked for {elapsed:.2f}s; hard timeout not enforced"
    tool_msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert tool_msgs
    assert "exceeded remaining time budget" in str(tool_msgs[0].content).lower()
