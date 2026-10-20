"""Lightweight, opt-in task guidance for NALLY's Harness experiment.

This module intentionally does not call an LLM. It chooses concise guidance for the
existing agent; evaluation must establish whether that guidance improves outcomes.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Literal

TaskMode = Literal[
    "general",
    "research",
    "document_analysis",
    "analysis",
    "creation",
    "planning",
    "execution",
    "problem_solving",
]


@dataclass(frozen=True)
class TaskProfile:
    """Cheap, inspectable task profile used to select operating guidance."""

    mode: TaskMode
    multi_step: bool


_MODE_PATTERNS: tuple[tuple[TaskMode, re.Pattern[str]], ...] = (
    (
        "document_analysis",
        re.compile(
            r"\b(?:in my library|in this document|in the (?:uploaded )?file|"
            r"according to (?:the )?(?:document|file|constitution|contract|paper)|"
            r"this pdf|uploaded document|from my notes)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "research",
        re.compile(
            r"\b(?:research|search (?:the web|online|for)|look up|latest|current|"
            r"recent|sources?|citations?|compare (?:the|these|current)|investigate)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "analysis",
        re.compile(
            r"\b(?:analy[sz]e|analysis|audit|review|inspect|assess|evaluate|examine|interpret)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "creation",
        re.compile(
            r"\b(?:write|draft|compose|create|generate|design|build me|produce|"
            r"prepare (?:a|an|the) (?:report|email|plan|document|presentation))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "planning",
        re.compile(
            r"\b(?:plan|roadmap|strategy|prioriti[sz]e|milestones?|trade-?offs?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "execution",
        re.compile(
            r"\b(?:implement|fix|refactor|run tests?|test (?:the|my|this)|"
            r"commit|push|deploy|change the code|update the repo|execute)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "problem_solving",
        re.compile(
            r"\b(?:solve|debug|troubleshoot|broken|error|failure|issue|"
            r"what went wrong|root cause|reduce (?:the|this)|improve)\b",
            re.IGNORECASE,
        ),
    ),
)

_MULTI_STEP_RE = re.compile(
    r"\b(?:step[- ]by[- ]step|end[- ]to[- ]end|whole|entire|all of|"
    r"complete(?:ly)?|multiple|multi[- ]step|from start to finish)\b",
    re.IGNORECASE,
)

_MODE_GUIDANCE: dict[TaskMode, str] = {
    "general": (
        "Answer the actual request directly and concisely. Prefer a short correct answer "
        "over process commentary. Do not call tools or expand the task unless they "
        "materially improve the answer."
    ),
    "research": (
        "Treat this as research with a hard preference for source-backed claims. "
        "Search for primary or official sources first; support material claims with "
        "citations or clear source names; mark uncertainty explicitly when evidence is "
        "thin or conflicting. Prefer fewer high-quality sources over many weak ones. "
        "Do not treat one failed search as proof that no answer exists. Stop once the "
        "key questions are adequately answered—do not keep searching for completeness theater."
    ),
    "document_analysis": (
        "Ground document-specific claims in retrieved passages. Search focused subtopics "
        "when the question spans several concepts, place source markers beside supported "
        "claims, and distinguish an exact phrase miss from absence of a relevant rule."
    ),
    "analysis": (
        "Analyze the available evidence before concluding. Separate observations from "
        "inferences and unknowns, compare plausible explanations, and present the most "
        "important findings and practical implications without inventing missing facts."
    ),
    "creation": (
        "Deliver the requested artifact in the requested format and audience/tone. Avoid "
        "explaining the process instead of producing the deliverable; check the output "
        "against the user's explicit constraints."
    ),
    "planning": (
        "Produce a concise, usable plan. Lead with the outcome and hard constraints, then "
        "list only the necessary steps with dependencies and success criteria. Prefer "
        "bullets over long prose. Cap elaboration: if a detail does not change a decision "
        "or risk, omit it. Do not invent milestones, ceremonies, or optional phases the "
        "user did not ask for."
    ),
    "execution": (
        "Make scoped changes using only permitted tools. Verify the intended outcome with "
        "tests or a direct check, report what actually changed, and do not claim success "
        "because a command or patch merely completed."
    ),
    "problem_solving": (
        "Diagnose before acting. State the most likely cause in one or two sentences, "
        "propose the smallest safe fix, and say how to verify it. Prefer a concrete "
        "corrected snippet or command over a long post-mortem. Avoid unrelated refactors "
        "and do not expand into a general tutorial unless asked."
    ),
}


def harness_enabled() -> bool:
    """Return whether experimental Harness guidance is enabled (off by default)."""
    return os.getenv("NALLY_HARNESS_ENABLED", "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def classify_task(user_text: str) -> TaskProfile:
    """Classify task intent with cheap heuristics; this is guidance, not a safety gate."""
    text = (user_text or "").strip()
    mode: TaskMode = "general"
    for candidate, pattern in _MODE_PATTERNS:
        if pattern.search(text):
            mode = candidate
            break
    multi_step = bool(_MULTI_STEP_RE.search(text)) or len(text) >= 500
    return TaskProfile(mode=mode, multi_step=multi_step)


def build_harness_guidance(user_text: str) -> str:
    """Build a compact system instruction for the current task without another LLM call."""
    profile = classify_task(user_text)
    guidance = [
        "HARNESS EXPERIMENT: apply the following task policy while preserving all existing "
        "security, authorization, session-isolation, tool, and time-budget rules.",
        f"Selected task mode: {profile.mode}.",
        _MODE_GUIDANCE[profile.mode],
    ]
    if profile.multi_step:
        guidance.append(
            "This appears multi-step. Break it into only the necessary subgoals, use "
            "intermediate results to adjust the approach, and verify the final acceptance "
            "criteria. Do not expose private chain-of-thought; report conclusions and evidence."
        )
    else:
        guidance.append(
            "Keep the workflow proportional to the request. Avoid a mandatory plan, extra "
            "reflection call, or verification step that adds no value."
        )
    guidance.append(
        "If evidence or a tool is insufficient, state the limitation instead of inventing "
        "a result. Stop when the request is adequately satisfied."
    )
    return "\n".join(guidance)
