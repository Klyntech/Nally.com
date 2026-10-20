# Harness paired evaluation protocol

## Purpose

This protocol compares NALLY's existing behavior (baseline) with the experimental task guidance in Harness. It does not assume Harness is better. Both variants must receive the same tasks, source fixtures, model/provider configuration, and comparable runtime conditions.

## Task set

Use `tests/fixtures/harness_eval_tasks.jsonl`, a 31-task initial set spanning direct answers, research, library/document analysis, creation, planning, repository execution, problem-solving, ambiguity, no-answer cases, and safe handling of hostile retrieved text.

This set is an initial pilot, not a fully validated gold benchmark. Before interpreting scores:
- review each success criterion;
- provision fixed document/code fixtures for tasks marked as requiring them;
- record exact model/provider and source snapshots;
- use human review for factual support, citations, and overall task completion.

## Run conditions

1. Pin the same commit, model/provider, tool configuration, and fixture snapshots for both variants.
2. Run with `NALLY_HARNESS_ENABLED=false` for baseline and `NALLY_HARNESS_ENABLED=true` for Harness.
3. Run each task three times when model/provider nondeterminism is material. Keep task IDs stable across variants.
4. Record each result as one JSON object per line. Do not put secrets or unrestricted private user data into result records.
5. Use `scripts/compare_harness_runs.py --baseline baseline.jsonl --harness harness.jsonl` to calculate paired and aggregate metrics.
6. Have a human reviewer judge factual claims and citation support where the task requires sources. Do not treat a model judge as ground truth.

## Result schema

Required fields:
- `task_id`: stable ID from the task set.
- `completed`: whether the user's actual objective was met, according to the task's success criteria.
- `claims_supported`, `claims_total`: human-reviewed counts of factual claims supported by the available evidence.
- `citations_valid`, `citations_total`: counts of citations that exist and support the associated claims.
- `cross_session_leak`: whether any information crossed principal/session boundaries.
- `latency_ms`: end-to-end latency for the same measurement boundary in both variants.
- `tool_calls`: total tool calls.
- `cost_usd`: provider-reported cost when available, otherwise `null`. Never substitute zero for unknown cost.

Example:
```json
{"task_id":"direct-01","completed":true,"claims_supported":1,"claims_total":1,"citations_valid":0,"citations_total":0,"cross_session_leak":false,"latency_ms":820,"tool_calls":0,"cost_usd":null}
```

## Metrics and interpretation

Compare:
- completion rate and paired task outcomes;
- claim support and citation validity for applicable tasks;
- p50/p95 latency;
- mean tool calls;
- mean cost across only tasks with known cost, alongside the count of tasks with known cost;
- security/isolation failures.

A task may have zero citations because none are needed; citation rate is undefined when no citations were expected. Review these cases rather than interpreting the null ratio as failure.

## Decision rules

- Any cross-session leak or permission-boundary violation is an immediate blocker.
- Do not enable Harness by default solely because a small pilot looks better.
- Keep it only if the improvement is repeatable and meaningful for task success or correctness, without unacceptable latency/cost regressions.
- If improvement is limited to document research or execution, consider category-specific activation instead of global activation.
- If outcomes are unchanged or worse, revise or remove the classifier/guidance rather than adding reflection loops to compensate.
- Record sample size, task-level disagreements, uncertainty, and known limitations with every result report.
