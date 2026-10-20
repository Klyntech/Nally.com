"""Tests for loop-level tool guards (approval + tool-loop detection)."""
from __future__ import annotations

import os

import pytest

from nally.agent.tool_guards import (
    ToolLoopTracker,
    check_tool_approval,
    hash_tool_call,
    is_dangerous_tool,
    reset_tracker,
    tracker_for,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("NALLY_TOOL_APPROVAL", raising=False)
    monkeypatch.delenv("NALLY_APPROVAL_MODE", raising=False)
    monkeypatch.delenv("NALLY_APPROVED_TOOLS", raising=False)
    monkeypatch.delenv("NALLY_TOOL_LOOP_GUARD", raising=False)
    monkeypatch.delenv("NALLY_TOOL_LOOP_MAX_REPEATS", raising=False)
    reset_tracker("test-session")
    yield
    reset_tracker("test-session")


def test_hash_stable_for_same_args():
    a = hash_tool_call("web_search", {"query": "capta", "max_results": 4})
    b = hash_tool_call("web_search", {"max_results": 4, "query": "capta"})
    assert a == b


def test_dangerous_tool_detection():
    assert is_dangerous_tool("run_command")
    assert is_dangerous_tool("file_write")
    assert not is_dangerous_tool("web_search")
    assert not is_dangerous_tool("memory_recall")


def test_approval_off_by_default_allows_shell():
    assert check_tool_approval("run_command") is None


def test_approval_allowlist_blocks_unlisted_shell(monkeypatch):
    monkeypatch.setenv("NALLY_TOOL_APPROVAL", "true")
    monkeypatch.setenv("NALLY_APPROVAL_MODE", "allowlist")
    monkeypatch.setenv("NALLY_APPROVED_TOOLS", "web_search")
    msg = check_tool_approval("run_command")
    assert msg and "blocked" in msg


def test_approval_allowlist_permits_listed(monkeypatch):
    monkeypatch.setenv("NALLY_TOOL_APPROVAL", "true")
    monkeypatch.setenv("NALLY_APPROVAL_MODE", "allowlist")
    monkeypatch.setenv("NALLY_APPROVED_TOOLS", "run_command,file_write")
    assert check_tool_approval("run_command") is None


def test_approval_deny_mode(monkeypatch):
    monkeypatch.setenv("NALLY_TOOL_APPROVAL", "true")
    monkeypatch.setenv("NALLY_APPROVAL_MODE", "deny")
    msg = check_tool_approval("run_command")
    assert msg and "deny" in msg


def test_tool_loop_escalates_then_blocks():
    tr = ToolLoopTracker()
    args = {"query": "same"}
    for i in range(1, 3):
        n, msg = tr.observe("web_search", args)
        assert msg is None
        assert n == i
    n, msg = tr.observe("web_search", args)
    assert n == 3
    assert msg and "tool-loop guard" in msg
    n, msg = tr.observe("web_search", args)
    assert n == 4
    assert msg and "terminated" in msg


def test_different_args_do_not_share_counter():
    tr = ToolLoopTracker()
    n, msg = tr.observe("web_search", {"query": "a"})
    assert n == 1 and msg is None
    n, msg = tr.observe("web_search", {"query": "a"})
    assert n == 2 and msg is None
    # different query is a separate identity
    n, msg = tr.observe("web_search", {"query": "b"})
    assert n == 1
    assert msg is None


def test_tracker_for_session_isolation():
    reset_tracker("s1")
    reset_tracker("s2")
    t1 = tracker_for("s1")
    t2 = tracker_for("s2")
    for _ in range(3):
        t1.observe("web_search", {"q": 1})
    n, msg = t2.observe("web_search", {"q": 1})
    assert n == 1
    assert msg is None
