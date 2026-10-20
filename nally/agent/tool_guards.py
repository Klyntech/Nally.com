"""Loop-level tool guards inspired by production agent harnesses (Hermes-style).

These are runtime mechanics, not task-mode prompt guidance:

1. Tool-loop detection — same tool + same args across turns escalates to a hard stop.
2. Dangerous-tool approval — shell and other high-risk tools require an allow policy.

Both are independent of NALLY_HARNESS_ENABLED (task guidance). Enable via:

- NALLY_TOOL_LOOP_GUARD=true (default: true)
- NALLY_TOOL_APPROVAL=true (default: false — opt-in until operators configure allowlists)
- NALLY_APPROVED_TOOLS=run_command,file_write  (comma list; empty = deny dangerous)
- NALLY_APPROVAL_MODE=deny|allowlist|allow_all
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

# Tools treated as high-risk when approval mode is active.
_DANGEROUS_TOOLS = frozenset(
    {
        "run_command",
        "file_write",
        # MCP tool names are free-form; match common destructive patterns below.
    }
)

_DANGEROUS_NAME_RE = re.compile(
    r"(shell|exec|bash|terminal|delete|rm_|remove|drop_|write_file|run_cmd)",
    re.IGNORECASE,
)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().casefold() in {"1", "true", "yes", "on"}


def tool_loop_guard_enabled() -> bool:
    return _env_bool("NALLY_TOOL_LOOP_GUARD", True)


def tool_approval_enabled() -> bool:
    return _env_bool("NALLY_TOOL_APPROVAL", False)


def approval_mode() -> str:
    """deny | allowlist | allow_all"""
    mode = os.getenv("NALLY_APPROVAL_MODE", "allowlist").strip().casefold()
    if mode in {"deny", "allowlist", "allow_all"}:
        return mode
    return "allowlist"


def approved_tool_names() -> set[str]:
    raw = os.getenv("NALLY_APPROVED_TOOLS", "").strip()
    if not raw:
        return set()
    return {p.strip() for p in raw.split(",") if p.strip()}


def is_dangerous_tool(name: str) -> bool:
    if name in _DANGEROUS_TOOLS:
        return True
    return bool(_DANGEROUS_NAME_RE.search(name or ""))


def check_tool_approval(name: str) -> str | None:
    """Return an error message if the tool is blocked; None if allowed."""
    if not tool_approval_enabled():
        return None
    if not is_dangerous_tool(name):
        return None
    mode = approval_mode()
    if mode == "allow_all":
        return None
    if mode == "deny":
        return (
            f"Error: tool '{name}' blocked by NALLY_TOOL_APPROVAL "
            f"(mode=deny). Dangerous tools are not permitted."
        )
    # allowlist
    if name in approved_tool_names():
        return None
    return (
        f"Error: tool '{name}' blocked by NALLY_TOOL_APPROVAL "
        f"(mode=allowlist). Add it to NALLY_APPROVED_TOOLS to permit."
    )


def _normalize_args(args: Any) -> Any:
    if isinstance(args, dict):
        return {k: _normalize_args(args[k]) for k in sorted(args)}
    if isinstance(args, list):
        return [_normalize_args(x) for x in args]
    if isinstance(args, str) and len(args) > 500:
        return args[:500]
    return args


def hash_tool_call(name: str, args: Any) -> str:
    payload = json.dumps(
        {"name": name, "args": _normalize_args(args)},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def max_tool_repeats() -> int:
    try:
        return max(2, int(os.getenv("NALLY_TOOL_LOOP_MAX_REPEATS", "3")))
    except ValueError:
        return 3


class ToolLoopTracker:
    """Tracks identical tool calls across the agent run (session-scoped)."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def observe(self, name: str, args: Any) -> tuple[int, str | None]:
        """Record a call. Returns (repeat_count, optional_block_message)."""
        if not tool_loop_guard_enabled():
            return 0, None
        key = hash_tool_call(name, args)
        self._counts[key] = self._counts.get(key, 0) + 1
        n = self._counts[key]
        limit = max_tool_repeats()
        if n < limit:
            return n, None
        if n == limit:
            return n, (
                f"Error: tool-loop guard — '{name}' was called {n} times with the same "
                f"arguments. Do not repeat this call; use the previous result or change approach."
            )
        # Beyond limit: harder stop signal for the model
        return n, (
            f"Error: tool-loop terminated — '{name}' repeated {n} times with identical "
            f"arguments. Further identical calls are blocked for this run."
        )


# Per-process trackers keyed by session_id (bounded).
_TRACKERS: dict[str, ToolLoopTracker] = {}
_TRACKER_MAX = 256


def tracker_for(session_id: str) -> ToolLoopTracker:
    sid = session_id or "default"
    if sid not in _TRACKERS:
        if len(_TRACKERS) >= _TRACKER_MAX:
            # Drop an arbitrary old entry
            try:
                _TRACKERS.pop(next(iter(_TRACKERS)))
            except StopIteration:
                pass
        _TRACKERS[sid] = ToolLoopTracker()
    return _TRACKERS[sid]


def reset_tracker(session_id: str) -> None:
    _TRACKERS.pop(session_id or "default", None)
