# Document-grounded research quality scorecard

This is the first product workflow to qualify for expansion: a user uploads a document through Telegram, asks a question, Nally retrieves relevant passages, and returns an answer with stable source markers. The API remains the service boundary; Telegram is only the first interface.

Do not expand the workflow until the evaluation set is reviewed and the gates below pass. Report the sample size and confidence limits with every score. Unit tests are necessary but are not a substitute for human review of factuality.

## Metrics and gates

| Metric | Measurement | Initial gate |
| --- | --- | ---: |
| Task completion | Percentage of curated research tasks that answer the question using the supplied documents, with no unsupported claims | >= 90% |
| Factual accuracy | Percentage of answer claims supported by the retrieved source text, reviewed by a human evaluator | >= 95% |
| Citation correctness | Percentage of cited source IDs that exist in the retrieved set and support the associated claim | >= 98% |
| Cross-session isolation | Adversarial tests where no fact, turn, or document from another principal/session appears | 100% |
| Failure recovery | Percentage of injected transient tool failures after which the agent completes or clearly reports a bounded failure | >= 95% |
| Latency | End-to-end p50 and p95 from accepted request to final response, measured separately for API and Telegram | Record baseline; p95 <= 20 s for document-only questions |
| Cost | Actual provider-reported input/output usage and cost per completed task; report unavailable usage as unknown, never zero | Establish a measured budget before rollout |

## Evaluation protocol

1. Maintain a versioned set of at least 30 questions across direct lookup, multi-passage synthesis, ambiguous queries, no-answer cases, long documents, and adversarial instructions embedded in documents.
2. Run each task three times against a fixed document snapshot and fixed model/provider configuration.
3. Store the code commit, model/provider, document fixture hash, retrieved source IDs, final answer, elapsed time, usage/cost when available, and evaluator result.
4. Have a reviewer label every factual claim as supported, contradicted, or unsupported, and every citation as valid, invalid, or insufficient.
5. Include negative tests: absent source passage, unrelated retrieved passage, invalid citation marker, cross-session query, timed-out provider, failed MCP tool, and interrupted multi-step task.
6. Report failures by category. Do not average away a security failure: cross-session leakage is an automatic release blocker regardless of other scores.
7. Re-run the complete suite after changes to retrieval, prompts, memory, providers, MCP policy, session identity, or citation formatting.

## Current evidence

The CI suite includes regression tests for:
- fact memory versus conversation-history context;
- per-principal API session namespaces and separate session retrieval;
- merged FTS/vector retrieval ordering and chunk deduplication;
- stable library chunk citations preserved when the model omits inline markers;
- MCP allowlist/policy enforcement, timeout conversion, and partial discovery failure;
- agent continuation after a tool fails;
- API auth, Telegram webhook secret enforcement, workspace containment, and fail-closed shell isolation.

These are automated regression checks, not yet a measured 30-task factuality benchmark. Do not report task completion, factual accuracy, production latency, or provider cost as measured until the evaluation dataset and production telemetry exist.

The hosted CI runner currently blocks Bubblewrap namespace setup with `RTM_NEWADDR: Operation not permitted`. In that environment, the real sandbox integration test verifies fail-closed behavior and skips the filesystem-isolation assertions. The argument-level regression tests still run, but a deployment smoke test on a host that permits Bubblewrap namespaces is required before claiming that the shell sandbox is operational.
