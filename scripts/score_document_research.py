"""Score human-annotated document-research evaluation records from JSONL."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

_REQUIRED = {
    "task_id",
    "completed",
    "claims_supported",
    "claims_total",
    "citations_valid",
    "citations_total",
    "cross_session_leak",
    "failure_injected",
    "recovered_after_failure",
    "latency_ms",
    "cost_usd",
}


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def _load_records(path: Path) -> list[dict[str, Any]]:
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(record, dict):
            raise ValueError(f"{path}:{line_number}: each record must be a JSON object")
        missing = _REQUIRED - record.keys()
        if missing:
            raise ValueError(
                f"{path}:{line_number}: missing required fields: {', '.join(sorted(missing))}"
            )
        for field in ("completed", "cross_session_leak", "failure_injected"):
            if not isinstance(record[field], bool):
                raise ValueError(f"{path}:{line_number}: {field} must be boolean")
        for field in ("claims_supported", "claims_total", "citations_valid", "citations_total"):
            value = record[field]
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"{path}:{line_number}: {field} must be a non-negative integer")
        if record["claims_supported"] > record["claims_total"]:
            raise ValueError(f"{path}:{line_number}: claims_supported exceeds claims_total")
        if record["citations_valid"] > record["citations_total"]:
            raise ValueError(f"{path}:{line_number}: citations_valid exceeds citations_total")
        latency = record["latency_ms"]
        if not isinstance(latency, (int, float)) or latency < 0:
            raise ValueError(f"{path}:{line_number}: latency_ms must be non-negative")
        cost = record["cost_usd"]
        if cost is not None and (not isinstance(cost, (int, float)) or cost < 0):
            raise ValueError(f"{path}:{line_number}: cost_usd must be non-negative or null")
        recovered = record["recovered_after_failure"]
        if recovered is not None and not isinstance(recovered, bool):
            raise ValueError(
                f"{path}:{line_number}: recovered_after_failure must be boolean or null"
            )
        if record["failure_injected"] and recovered is None:
            raise ValueError(
                f"{path}:{line_number}: failure-injected tasks need a recovery result"
            )
        records.append(record)
    if not records:
        raise ValueError(f"{path}: no evaluation records found")
    return records


def score_records(records: list[dict[str, Any]], max_cost_usd: float | None = None) -> dict[str, Any]:
    total = len(records)
    claims_total = sum(record["claims_total"] for record in records)
    claims_supported = sum(record["claims_supported"] for record in records)
    citations_total = sum(record["citations_total"] for record in records)
    citations_valid = sum(record["citations_valid"] for record in records)
    failures = [record for record in records if record["failure_injected"]]
    recovered = sum(record["recovered_after_failure"] is True for record in failures)
    known_costs = [float(record["cost_usd"]) for record in records if record["cost_usd"] is not None]
    completed_with_cost = [
        float(record["cost_usd"])
        for record in records
        if record["completed"] and record["cost_usd"] is not None
    ]
    latencies = [float(record["latency_ms"]) for record in records]
    leak_count = sum(record["cross_session_leak"] for record in records)

    metrics = {
        "sample_size": total,
        "task_completion_rate": _rate(sum(record["completed"] for record in records), total),
        "factual_accuracy": _rate(claims_supported, claims_total),
        "citation_correctness": _rate(citations_valid, citations_total),
        "cross_session_isolation_rate": _rate(total - leak_count, total),
        "cross_session_leaks": leak_count,
        "failure_recovery_rate": _rate(recovered, len(failures)),
        "injected_failures": len(failures),
        "latency_ms_p50": _percentile(latencies, 0.50),
        "latency_ms_p95": _percentile(latencies, 0.95),
        "cost_observed_tasks": len(known_costs),
        "cost_unknown_tasks": total - len(known_costs),
        "known_total_cost_usd": sum(known_costs),
        "mean_cost_per_completed_task_usd": _rate(
            sum(completed_with_cost), len(completed_with_cost)
        ),
        "cost_budget_usd": max_cost_usd,
    }
    gates = {
        "task_completion": metrics["task_completion_rate"] is not None
        and metrics["task_completion_rate"] >= 0.90,
        "factual_accuracy": metrics["factual_accuracy"] is not None
        and metrics["factual_accuracy"] >= 0.95,
        "citation_correctness": metrics["citation_correctness"] is not None
        and metrics["citation_correctness"] >= 0.98,
        "cross_session_isolation": leak_count == 0,
        "failure_recovery": metrics["failure_recovery_rate"] is not None
        and metrics["failure_recovery_rate"] >= 0.95,
        "latency": metrics["latency_ms_p95"] is not None
        and metrics["latency_ms_p95"] <= 20_000,
        "cost": max_cost_usd is not None
        and len(known_costs) == total
        and metrics["mean_cost_per_completed_task_usd"] is not None
        and metrics["mean_cost_per_completed_task_usd"] <= max_cost_usd,
    }
    return {"metrics": metrics, "gates": gates, "all_gates_pass": all(gates.values())}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path, help="Human-annotated evaluation results in JSONL format")
    parser.add_argument(
        "--max-cost-usd",
        type=float,
        default=None,
        help="Required cost budget for the cost gate (average per completed task)",
    )
    parser.add_argument(
        "--check-gates",
        action="store_true",
        help="Exit with status 1 unless every quality gate passes",
    )
    args = parser.parse_args(argv)
    if args.max_cost_usd is not None and args.max_cost_usd < 0:
        parser.error("--max-cost-usd must be non-negative")
    if args.check_gates and args.max_cost_usd is None:
        parser.error("--check-gates requires --max-cost-usd; cost is not assumed to be zero")

    try:
        records = _load_records(args.results)
        report = score_records(records, max_cost_usd=args.max_cost_usd)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if args.check_gates and not report["all_gates_pass"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
