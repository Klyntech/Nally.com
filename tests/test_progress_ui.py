from nally.agent.progress import format_tool_detail, tool_label
from nally.telegram.progress import ProgressTracker
from nally.agent.progress import ProgressEvent


def test_tool_labels():
    assert "library" in tool_label("library_search").lower()
    assert "web" in tool_label("web_search").lower()
    assert "command" in tool_label("run_command").lower()


def test_format_detail_redacts_and_truncates():
    d = format_tool_detail("web_search", {"query": "x" * 200})
    assert len(d) <= 90
    d2 = format_tool_detail("run_command", {"command": "echo token=secretvalue"})
    assert "REDACTED" in d2 or "secretvalue" not in d2


def test_progress_tracker_builds_lines():
    t = ProgressTracker(min_interval_s=0)
    text = t.on_event(
        ProgressEvent(kind="tool_start", tool="library_search", detail="hearsay")
    )
    assert text is not None
    assert "Searching library" in text
    assert "hearsay" in text
    text2 = t.on_event(
        ProgressEvent(
            kind="tool_end", tool="library_search", detail="hearsay", status="ok"
        )
    )
    assert text2 is not None
    assert "✓" in text2
