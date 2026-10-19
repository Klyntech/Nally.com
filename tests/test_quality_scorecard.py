"""Tests for the document research evaluation scorecard."""
from __future__ import annotations

from scripts.score_document_research import score_records


def _record(task_id: str, **updates):
    record = {
        "task_id": task_id,
        "completed": True,
        "claims_supported": 2,
        "claims_total": 2,
        "citations_valid": 1,
        "citations_total": 1,
        "cross_session_leak": False,
        "failure_injected": False,
        "recovered_after_failure": None,
        "latency_ms": 1000,
        "cost_usd": 0.01,
    }
    record.update(updates)
    return record


def test_scorecard_calculates_rates_latency_and_cost() -> None:
    records = [
        _record("task-1", latency_ms=100),
        _record(
            "task-2",
            completed=False,
            claims_supported=1,
            claims_total=2,
            citations_valid=0,
            citations_total=1,
            failure_injected=True,
            recovered_after_failure=False,
            latency_ms=300,
            cost_usd=None,
        ),
    ]

    report = score_records(records, max_cost_usd=0.02)
    metrics = report["metrics"]

    assert metrics["task_completion_rate"] == 0.5
    assert metrics["factual_accuracy"] == 0.75
    assert metrics["citation_correctness"] == 0.5
    assert metrics["cross_session_isolation_rate"] == 1.0
    assert metrics["failure_recovery_rate"] == 0.0
    assert metrics["latency_ms_p50"] == 200
    assert metrics["latency_ms_p95"] == 290
    assert metrics["cost_unknown_tasks"] == 1
    assert metrics["mean_cost_per_completed_task_usd"] == 0.01
    assert not report["all_gates_pass"]


def test_scorecard_gates_pass_only_with_complete_measurements() -> None:
    records = [
        _record("task-1", failure_injected=True, recovered_after_failure=True),
        _record("task-2", latency_ms=1200, cost_usd=0.015),
    ]

    report = score_records(records, max_cost_usd=0.02)

    assert report["all_gates_pass"]
    assert all(report["gates"].values())
