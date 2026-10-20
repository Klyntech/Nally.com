"""Tests for paired Harness run comparison."""
from __future__ import annotations

import pytest

from scripts.compare_harness_runs import compare


def _record(
    task_id: str,
    *,
    completed: bool,
    latency_ms: int = 1000,
    tool_calls: int = 1,
    cost_usd: float | None = 0.01,
    cross_session_leak: bool = False,
) -> dict:
    return {
        "task_id": task_id,
        "completed": completed,
        "claims_supported": 4,
        "claims_total": 4,
        "citations_valid": 2,
        "citations_total": 2,
        "cross_session_leak": cross_session_leak,
        "latency_ms": latency_ms,
        "tool_calls": tool_calls,
        "cost_usd": cost_usd,
    }


def test_compare_reports_paired_completion_and_resource_metrics() -> None:
    baseline = {
        "a": _record("a", completed=False, latency_ms=1000),
        "b": _record("b", completed=True, latency_ms=2000),
    }
    harness = {
        "a": _record("a", completed=True, latency_ms=1500),
        "b": _record("b", completed=True, latency_ms=1800),
    }

    result = compare(baseline, harness)

    assert result["paired_completion"] == {
        "harness_only_successes": 1,
        "baseline_only_successes": 0,
        "same_completion_outcome": 1,
    }
    assert result["harness"]["completion_rate"] == 1.0
    assert result["harness"]["claim_support_rate"] == 1.0
    assert result["harness"]["mean_known_cost_usd"] == pytest.approx(0.01)
    assert not result["release_blocker"]


def test_compare_rejects_unpaired_task_sets() -> None:
    with pytest.raises(ValueError, match="same task IDs"):
        compare({"a": _record("a", completed=True)}, {})


def test_any_cross_session_leak_is_a_release_blocker() -> None:
    baseline = {"a": _record("a", completed=True)}
    harness = {"a": _record("a", completed=True, cross_session_leak=True)}

    assert compare(baseline, harness)["release_blocker"]


def test_unknown_cost_is_not_counted_as_zero() -> None:
    baseline = {"a": _record("a", completed=True, cost_usd=None)}
    harness = {"a": _record("a", completed=True, cost_usd=0.02)}

    result = compare(baseline, harness)

    assert result["baseline"]["mean_known_cost_usd"] is None
    assert result["baseline"]["known_cost_tasks"] == 0
