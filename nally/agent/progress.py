"""Agent progress events for live UI (Telegram status, logs, etc.)."""
from __future__ import annotations

import contextvars
import re
from dataclasses import dataclass
from typing import Any, Callable, Literal

ProgressKind = Literal["thinking", "tool_start", "tool_end", "done", "error"]
ProgressStatus = Literal["running", "ok", "error"]

ProgressCallback = Callable[["ProgressEvent"], None]

_progress_cb: contextvars.ContextVar[ProgressCallback | None] = contextvars.ContextVar(
    "nally_progress_cb", default=None
)

_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|token|secret|api[_-]?key)\b\s*[:=]\s*\S+"
)


@dataclass(frozen=True)
class ProgressEvent:
    kind: ProgressKind
    tool: str | None = None
    detail: str = ""
    status: ProgressStatus = "running"


def set_progress_callback(cb: ProgressCallback | None) -> contextvars.Token:
    return _progress_cb.set(cb)


def reset_progress_callback(token: contextvars.Token) -> None:
    _progress_cb.reset(token)


def emit_progress(event: ProgressEvent) -> None:
    cb = _progress_cb.get()
    if cb is None:
        return
    try:
        cb(event)
    except Exception:
        # Progress must never break the agent turn.
        pass


def _truncate(text: str, limit: int = 90) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    text = _SECRET_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def format_tool_detail(name: str, args: dict[str, Any] | None) -> str:
    args = args or {}
    if name == "web_search":
        return _truncate(str(args.get("query") or ""))
    if name == "fetch":
        return _truncate(str(args.get("url") or args.get("path") or ""))
    if name == "library_search":
        return _truncate(str(args.get("query") or ""))
    if name in {"library_get", "library_rename"}:
        return _truncate(
            str(args.get("document_slug") or args.get("current_slug") or "")
        )
    if name == "library_list":
        return "library"
    if name in {"file_read", "file_write", "file_list"}:
        return _truncate(str(args.get("path") or "."))
    if name == "run_command":
        return _truncate(str(args.get("command") or args.get("cmd") or ""))
    if name.startswith("memory_"):
        return _truncate(str(args.get("key") or name.replace("memory_", "")))
    # Generic: first string-ish arg
    for key in ("query", "path", "url", "command", "name", "title"):
        if key in args and args[key]:
            return _truncate(str(args[key]))
    if args:
        return _truncate(str(next(iter(args.values()))))
    return ""


def tool_label(name: str) -> str:
    labels = {
        "web_search": "Searching web",
        "fetch": "Opening URL",
        "library_search": "Searching library",
        "library_get": "Reading library",
        "library_list": "Listing library",
        "library_rename": "Renaming library doc",
        "file_read": "Reading file",
        "file_write": "Writing file",
        "file_list": "Listing files",
        "run_command": "Running command",
        "memory_remember": "Remembering",
        "memory_recall": "Recalling memory",
        "memory_forget": "Forgetting",
    }
    if name in labels:
        return labels[name]
    if name.startswith("mcp_"):
        return f"Using {name}"
    return f"Using {name}"
