"""Compare paired, human-reviewed baseline and Harness evaluation JSONL runs."""
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
    "latency_ms",
    "tool_calls",
    "cost_usd",
}


def _load(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(record, dict):
            raise ValueError(f"{path}:{line_number}: record must be a JSON object")
        missing = _REQUIRED - record.keys()
        if missing:
            raise ValueError(
                f"{path}:{line_number}: missing fields: {', '.join(sorted(missing))}"
            )
        task_id = record["task_id"]
        if not isinstance(task_id, str) or not task_id:
            raise ValueError(f"{path}:{line_number}: task_id must be a non-empty string")
        if task_id in records:
            raise ValueError(f"{path}:{line_number}: duplicate task_id {task_id!r}")
        for field in ("completed", "cross_session_leak"):
            if not isinstance(record[field], bool):
                raise ValueError(f"{path}:{line_number}: {field} must be boolean")
        for field in (
            "claims_supported",
            "claims_total",
            "citations_valid",
            "citations_total",
            "latency_ms",
            "tool_calls",
        ):
            if not isinstance(record[field], (int, float)) or isinstance(record[field], bool):
                raise ValueError(f"{path}:{line_number}: {field} must be numeric")
            if record[field] < 0:
                raise ValueError(f"{path}:{line_number}: {field} must be non-negative")
        cost = record["cost_usd"]
        if cost is not None and (
            not isinstance(cost, (int, float)) or isinstance(cost, bool) or cost < 0
        ):
            raise ValueError(f"{path}:{line_number}: cost_usd must be non-negative or null")
        records[task_id] = record
    return records


def _rate(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - position) + ordered[high] * (position - low)


def _summarize(records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    values = list(records.values())
    claim_supported = sum(r["claims_supported"] for r in values)
    claim_total = sum(r["claims_total"] for r in values)
    citations_valid = sum(r["citations_valid"] for r in values)
    citations_total = sum(r["citations_total"] for r in values)
    latencies = [float(r["latency_ms"]) for r in values]
    tool_calls = [float(r["tool_calls"]) for r in values]
    costs = [float(r["cost_usd"]) for r in values if r["cost_usd"] is not None]
    return {
        "tasks": len(values),
        "completion_rate": _rate(sum(r["completed"] for r in values), len(values)),
        "claim_support_rate": _rate(claim_supported, claim_total),
        "citation_validity_rate": _rate(citations_valid, citations_total),
        "latency_ms_p50": _percentile(latencies, 0.50),
        "latency_ms_p95": _percentile(latencies, 0.95),
        "mean_tool_calls": _rate(sum(tool_calls), len(tool_calls)),
        "mean_known_cost_usd": _rate(sum(costs), len(costs)),
        "known_cost_tasks": len(costs),
        "cross_session_leaks": sum(r["cross_session_leak"] for r in values),
    }


def compare(baseline: dict[str, dict[str, Any]], harness: dict[str, dict[str, Any]]) -> dict[str, Any]:
    baseline_ids, harness_ids = set(baseline), set(harness)
    if baseline_ids != harness_ids:
        raise ValueError(
            "runs must contain the same task IDs; "
            f"baseline-only={sorted(baseline_ids - harness_ids)}, "
            f"harness-only={sorted(harness_ids - baseline_ids)}"
        )
    improved = regressed = tied = 0
    for task_id in baseline:
        old, new = baseline[task_id]["completed"], harness[task_id]["completed"]
        if new and not old:
            improved += 1
        elif old and not new:
            regressed += 1
        else:
            tied += 1
    return {
        "baseline": _summarize(baseline),
        "harness": _summarize(harness),
        "paired_completion": {
            "harness_only_successes": improved,
            "baseline_only_successes": regressed,
            "same_completion_outcome": tied,
        },
        "release_blocker": (
            _summarize(baseline)["cross_session_leaks"] > 0
            or _summarize(harness)["cross_session_leaks"] > 0
        ),
        "notes": [
            "Use identical task IDs, source fixtures, model/provider, and run conditions.",
            "Cost averages include only records with reported cost; unknown cost is not zero.",
            "Small samples are directional evidence, not proof of general improvement.",
            "Any cross-session leak blocks release regardless of aggregate scores.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path, help="Baseline annotated JSONL")
    parser.add_argument("--harness", required=True, type=Path, help="Harness annotated JSONL")
    args = parser.parse_args()
    try:
        result = compare(_load(args.baseline), _load(args.harness))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["release_blocker"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
