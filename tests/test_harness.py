"""Regression tests for opt-in Harness task guidance."""
from __future__ import annotations

from nally.agent.harness import (
    build_harness_guidance,
    classify_task,
    harness_enabled,
)


def test_document_question_uses_document_analysis_mode() -> None:
    profile = classify_task("In my library, what does the Constitution say about child abuse?")
    assert profile.mode == "document_analysis"
    assert "retrieved passages" in build_harness_guidance(
        "In my library, what does the Constitution say about child abuse?"
    )


def test_current_information_uses_research_mode() -> None:
    profile = classify_task("Research the latest changes and cite your sources.")
    assert profile.mode == "research"


def test_repository_analysis_uses_analysis_mode() -> None:
    profile = classify_task("Analyze my repo and identify architectural risks.")
    assert profile.mode == "analysis"


def test_creation_request_uses_creation_mode() -> None:
    profile = classify_task("Draft a concise project proposal for this feature.")
    assert profile.mode == "creation"


def test_execution_request_uses_execution_mode() -> None:
    profile = classify_task("Run tests and fix the failing implementation.")
    assert profile.mode == "execution"


def test_ambiguous_simple_question_stays_general() -> None:
    profile = classify_task("What is a variable?")
    assert profile.mode == "general"
    assert not profile.multi_step


def test_multi_step_task_gets_bounded_decomposition_guidance() -> None:
    guidance = build_harness_guidance("Fix the entire project end-to-end.")
    assert "Selected task mode: execution." in guidance
    assert "necessary subgoals" in guidance
    assert "Do not expose private chain-of-thought" in guidance


def test_harness_flag_is_off_by_default(monkeypatch) -> None:
    monkeypatch.delenv("NALLY_HARNESS_ENABLED", raising=False)
    assert not harness_enabled()


def test_harness_flag_accepts_explicit_true_values(monkeypatch) -> None:
    for value in ("1", "true", "YES", "on"):
        monkeypatch.setenv("NALLY_HARNESS_ENABLED", value)
        assert harness_enabled()


def test_harness_flag_rejects_other_values(monkeypatch) -> None:
    for value in ("0", "false", "off", "maybe"):
        monkeypatch.setenv("NALLY_HARNESS_ENABLED", value)
        assert not harness_enabled()


def test_research_guidance_requires_sources_and_uncertainty():
    g = build_harness_guidance("Research current CAPTA requirements and cite sources")
    assert "Selected task mode: research." in g
    low = g.lower()
    assert "source" in low or "citation" in low
    assert "uncertain" in low


def test_planning_guidance_prefers_concise_steps():
    g = build_harness_guidance("Plan a 3-day itinerary for Lagos with safety constraints")
    assert "Selected task mode: planning." in g
    low = g.lower()
    assert "concise" in low or "bullet" in low
    assert "omit" in low or "ceremony" in low or "elaborat" in low


def test_problem_solving_guidance_prefers_smallest_fix():
    g = build_harness_guidance("Debug why my Python sum loop prints the wrong value")
    assert "Selected task mode: problem_solving." in g
    low = g.lower()
    assert "smallest" in low or "likely cause" in low
    assert "verify" in low
