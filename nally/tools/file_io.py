"""Sandboxed file read/write/list under WORKSPACE."""
from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

from nally.config import MAX_TOOL_OUTPUT, WORKSPACE


def _safe(path: str) -> Path:
    """Resolve a workspace-relative path and reject traversal and symlink escapes."""
    root = WORKSPACE.resolve()
    root.mkdir(parents=True, exist_ok=True)

    requested = Path(path or ".")
    if requested.is_absolute():
        raise ValueError("Absolute paths are not allowed")

    target = (root / requested).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("Path escapes workspace") from exc
    return target


@tool
def file_read(path: str) -> str:
    """Read a text file relative to the workspace root."""
    try:
        p = _safe(path)
        if not p.is_file():
            return f"Error: not a file: {path}"
        data = p.read_text(encoding="utf-8", errors="replace")
        if len(data) > MAX_TOOL_OUTPUT:
            data = data[:MAX_TOOL_OUTPUT] + "\n...[truncated]"
        return data
    except Exception as e:
        return f"Error: {e}"


@tool
def file_write(path: str, content: str) -> str:
    """Write text to a file relative to the workspace root (creates parents)."""
    try:
        p = _safe(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Re-check after creating parent directories to catch symlinked parents.
        p = _safe(path)
        p.write_text(content or "", encoding="utf-8")
        return f"Wrote {len(content or '')} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


@tool
def file_list(path: str = ".") -> str:
    """List files and directories under a workspace-relative path."""
    try:
        p = _safe(path or ".")
        if not p.exists():
            return f"Error: path does not exist: {path}"
        if p.is_file():
            return f"FILE {path}"
        lines = []
        for child in sorted(p.iterdir()):
            # Do not follow an escaped symlink when listing entries.
            try:
                child.resolve().relative_to(WORKSPACE.resolve())
            except ValueError:
                continue
            kind = "DIR " if child.is_dir() else "FILE"
            lines.append(f"{kind} {child.name}")
        return "\n".join(lines) if lines else "(empty)"
    except Exception as e:
        return f"Error: {e}"
