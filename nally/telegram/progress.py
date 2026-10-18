"""Format and rate-limit live Thinking… status for Telegram."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from nally.agent.progress import ProgressEvent, tool_label


@dataclass
class ProgressTracker:
    """Build status text from progress events; throttle Telegram edits."""

    max_lines: int = 8
    min_interval_s: float = 1.2
    _lines: list[str] = field(default_factory=list)
    _last_emit: float = 0.0
    _last_text: str = "Thinking…"

    def on_event(self, event: ProgressEvent) -> str | None:
        """Apply event; return new status text if an edit should be sent."""
        line = self._line_for(event)
        if line:
            if event.kind == "tool_end" and self._lines:
                # Replace last running line with completed marker when same tool.
                prev = self._lines[-1]
                if prev.startswith("…") and event.tool and event.tool in prev:
                    self._lines[-1] = line
                else:
                    self._lines.append(line)
            else:
                self._lines.append(line)
            if len(self._lines) > self.max_lines:
                self._lines = self._lines[-self.max_lines :]

        text = self.render()
        now = time.monotonic()
        if text == self._last_text:
            return None
        if self._last_emit and (now - self._last_emit) < self.min_interval_s:
            if event.kind not in {"done", "error"}:
                return None
        self._last_emit = now
        self._last_text = text
        return text

    def render(self) -> str:
        if not self._lines:
            return "Thinking…"
        body = "\n".join(self._lines)
        return f"Thinking…\n{body}"

    def force_text(self) -> str:
        text = self.render()
        self._last_text = text
        self._last_emit = time.monotonic()
        return text

    def _line_for(self, event: ProgressEvent) -> str | None:
        if event.kind == "thinking":
            return None  # header only
        if event.kind == "tool_start":
            label = tool_label(event.tool or "tool")
            detail = (event.detail or "").strip()
            if detail:
                return f"… {label}: {detail}"
            return f"… {label}"
        if event.kind == "tool_end":
            label = tool_label(event.tool or "tool")
            detail = (event.detail or "").strip()
            mark = "✓" if event.status == "ok" else "✗"
            if detail:
                return f"{mark} {label}: {detail}"
            return f"{mark} {label}"
        if event.kind == "error":
            return f"✗ {event.detail or 'error'}"
        if event.kind == "done":
            return None
        return None
