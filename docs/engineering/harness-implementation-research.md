# Harness implementation research and design decision

Date: 2026-10-19
Repository: Klyntech/Nally.com
Experiment branch: experiment/harness-baseline

## Executive decision

Do not build a multi-agent supervisor, mandatory planner, reflection loop, or second evaluator call into every request. NALLY already has a LangGraph ReAct-style loop, tools, provider fallback, session-scoped memory, source-citation preservation, and hard iteration/tool/time budgets. A second agent loop would duplicate orchestration and increase latency/cost before there is evidence it improves results.

The first Harness experiment should be a small, opt-in policy layer that:
1. classifies the user's request into a coarse work mode without another LLM call;
2. adds concise, task-specific operating guidance to the existing system prompt;
3. preserves existing tools, memory/session identity, permissions, and budget limits;
4. leaves the existing baseline selectable with an environment flag;
5. records mode selection in deterministic unit tests and is evaluated against the same task set with Harness off and on.

This is a testable hypothesis, not a claim that a lexical classifier improves model quality. Keep it only if evaluation shows a meaningful benefit.

## NALLY's starting point

Inspection of `nally/agent/graph.py`, `nally/agent/prompts.py`, and `docs/quality/document-research-scorecard.md` shows:
- a single LangGraph agent already cycles between LLM decisions and tool calls;
- tools include library retrieval, web search, memory, MCP and workspace tools;
- explicit standalone search requests use a fast direct-search path;
- graph execution already has iteration, tool-call and wall-time budgets;
- memory is loaded into session-scoped context and saved after the turn;
- document source markers dropped by the model are appended as a fallback;
- an existing scorecard calls for a curated task set, claim/citation review, failure recovery, latency, and cost measurement.

The immediate weakness is not a lack of another loop. It is that one general system prompt has to guide many task types, while there is no demonstrated Harness-on versus Harness-off result set. The existing research scorecard also states that the full 30-task benchmark has not yet been run.

## Source review

### 1. Anthropic, "Building effective agents" (engineering guidance)
https://www.anthropic.com/engineering/building-effective-agents

The article distinguishes fixed workflows from dynamic agents, recommends starting with the simplest approach, and adding complexity only when measured results justify it. It describes routing for distinct input categories, evaluator-optimizer loops when criteria are clear, and the latency/cost and compounding-error trade-offs of autonomous agents.

**Fit for NALLY:** use small task-mode guidance and explicit evaluation first. Do not add evaluator loops or multi-agent orchestration globally. Keep the existing agent for tasks whose next step cannot be predicted.

### 2. Anthropic, "Demystifying evals for AI agents" (2026)
https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents

The article focuses on evaluation as the means to make agent behavior visible, diagnose failures, and detect regressions. Evaluation complexity should match the system and task.

**Fit for NALLY:** establish a repeatable baseline and evaluate end-to-end outcomes, not the number of plans or intermediate steps. Reuse NALLY's existing scorecard and extend it to general-purpose task types. Human review is needed for factual support and usefulness; deterministic checks should cover tool routing, citations, isolation, and budgets.

### 3. OpenAI, "Evaluate agent workflows" (official documentation)
https://developers.openai.com/api/docs/guides/agent-evals

The guide recommends traces, datasets, graders, and evaluation runs to identify whether the agent chose the right tool, respected instructions, and improved after a workflow change.

**Fit for NALLY:** record per-task mode, tool activity, result status, elapsed time, and known usage/cost when available. Avoid logging secrets or unrestricted user content. Use a versioned task set and compare baseline and Harness under the same model/provider and document fixtures.

### 4. LangGraph persistence and architecture documentation
https://reference.langchain.com/python/langgraph/overview
https://langchain-ai.github.io/langgraph/concepts/durable_execution/

LangGraph already supports stateful, multi-step execution and persistence patterns. These capabilities should be used where the product needs durable state, recovery, or human approval; they are not a reason to add another orchestration layer automatically.

**Fit for NALLY:** extend the existing graph incrementally. Do not introduce a second graph, checkpointer, or persistent planning state in the first experiment. Existing memory/session boundaries and hard budgets remain authoritative.

### 5. Ragas evaluation metrics
https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/

The framework distinguishes retrieval measures (such as context precision/recall), answer-grounding and relevance measures, and agent/tool-use measures. Some metrics use an LLM judge and can be nondeterministic.

**Fit for NALLY:** start with a few interpretable signals: task success, factual claim support, citation correctness, correct tool use, recovery after injected failures, latency, and cost. Use human labels for a small gold set. Do not treat one LLM-judge score as ground truth.

### 6. ReAct paper (Yao et al., 2022)
https://arxiv.org/abs/2210.03629

ReAct interleaves model reasoning with actions and observations from external tools. Its experiments show that tool interaction can improve some knowledge-intensive and interactive tasks compared with reasoning-only or action-only baselines.

**Fit for NALLY:** the existing ReAct-like graph already uses this pattern. Keep the core loop. Improve how it chooses and conducts work, rather than replacing it with a duplicate loop. Evaluate tool selection and evidence quality.

### 7. Reflexion paper (Shinn et al., NeurIPS 2023)
https://papers.neurips.cc/paper_files/paper/2023/hash/1b44b878bb782e6954cd888628510e90-Abstract-Conference.html

Reflexion uses feedback and episodic textual reflections to influence later attempts. Its reported results are benchmark-specific and do not imply that self-critique helps every conversational task.

**Fit for NALLY:** do not add persistent self-reflection memory in the first implementation. It adds complexity and risks retaining incorrect self-assessments. Revisit only for a task with objective feedback, repeatable failures, and a controlled test showing improvement.

## Chosen first implementation

### In scope
- A deterministic, low-cost task profile: direct/general, research, document analysis, creation, planning, execution, or problem-solving; plus a coarse multi-step signal.
- Concise mode-specific guidance that encourages source checking for research, source-grounded claims for document analysis, artifact completion for creation, explicit constraints for planning, and verification for execution/problem-solving.
- An environment flag, `NALLY_HARNESS_ENABLED`, so the same code can run baseline and experimental variants.
- Unit tests for classification and prompt guidance.
- A versioned evaluation protocol and results schema for baseline-versus-Harness runs.

### Explicitly out of scope for the first pass
- Mandatory planning calls for every prompt.
- Multiple agents, parallel voting, or a supervisor-worker hierarchy.
- Self-critique/revision loops on every response.
- Persistent plans or reflection memory.
- Automatic model escalation or model routing before quality and cost baselines exist.
- Any relaxation of authorization, privacy, session isolation, tool policy, or execution sandboxing.

## Evaluation plan

Use the same curated tasks for baseline and Harness. Begin with at least 30 representative tasks across:
- simple direct questions;
- current-information research;
- document/library lookup and multi-passage synthesis;
- creation/writing tasks;
- planning and decision support;
- software troubleshooting or multi-step execution;
- ambiguous requests;
- no-answer / insufficient-evidence cases;
- tool/provider timeout and recovery;
- adversarial instructions embedded in retrieved content.

Where stochasticity matters, run each variant three times with the same model/provider and fixed source fixtures. Record the commit, flag setting, model/provider, task ID, expected outcome, response, relevant source IDs, tool calls, elapsed time, usage/cost if reported, and reviewer labels.

Primary outcomes:
- task completion / goal accuracy;
- supported factual claims and citation correctness where applicable;
- correct tool use and recovery;
- p50/p95 latency;
- measured provider cost per completed task;
- security/isolation violations (zero tolerance).

Compare paired task outcomes, not just aggregate averages. Report sample size and uncertainty. Any cross-session leak or permission-boundary violation is a release blocker. A small pilot can reveal regressions but cannot establish universal improvement.

## Decision gate

Keep Harness enabled by default only if a reviewed evaluation shows an improvement in task completion or important correctness metrics without an unacceptable increase in latency/cost or any security regression. If gains are confined to a task category, enable it only for that category. If the difference is negligible or negative, simplify or remove the experiment.

## Important limitation

The task classifier is heuristic. Its purpose is to select lightweight guidance, not to prove intent. Classification errors and the effect of the guidance must be measured. The feature flag defaults to off for the initial controlled experiment.
