"""Tests for stable source references in document-grounded answers."""
from __future__ import annotations

from langchain_core.messages import ToolMessage

from nally.agent.graph import _append_library_citations
from nally.library.store import SearchHit
from nally.tools import library_tools


def test_library_search_emits_stable_document_chunk_reference(monkeypatch) -> None:
    hit = SearchHit(
        document_id=1,
        document_title="Evidence Act",
        document_slug="evidence-act",
        section_label="Section 1",
        content="A passage about evidence.",
        score=0.9,
        method="fts",
        ordinal=4,
    )

    class FakeLibraryStore:
        def search(self, query, *, limit, document_slug):
            return [hit]

    monkeypatch.setattr(library_tools, "get_library_store", FakeLibraryStore)

    result = library_tools.library_search.invoke({"query": "evidence"})

    assert "[source:evidence-act#chunk-4]" in result
    assert "Evidence Act · Section 1" in result


def test_final_answer_appends_citations_lost_by_the_model() -> None:
    tool_message = ToolMessage(
        content=(
            "[1] Evidence Act · Section 1 [source:evidence-act#chunk-4] "
            "(score=0.900, via=fts)\nA passage about evidence."
        ),
        tool_call_id="call-1",
        name="library_search",
    )

    answer = _append_library_citations("The passage establishes the rule.", [tool_message])

    assert answer.startswith("The passage establishes the rule.")
    assert "Library sources:" in answer
    assert "[source:evidence-act#chunk-4] Evidence Act · Section 1" in answer


def test_final_answer_does_not_duplicate_citations_already_present() -> None:
    tool_message = ToolMessage(
        content="[1] Evidence Act · Section 1 [source:evidence-act#chunk-4] (score=0.9)",
        tool_call_id="call-1",
        name="library_search",
    )
    answer = "The rule is stated in [source:evidence-act#chunk-4]."

    assert _append_library_citations(answer, [tool_message]) == answer


def test_final_answer_appends_only_missing_retrieved_citations() -> None:
    first = ToolMessage(
        content="[1] Evidence Act · Section 1 [source:evidence-act#chunk-4] (score=0.9)",
        tool_call_id="call-1",
        name="library_search",
    )
    second = ToolMessage(
        content="[2] Constitution · Article 12 [source:constitution#chunk-7] (score=0.8)",
        tool_call_id="call-2",
        name="library_search",
    )
    answer = "The rule is stated in [source:evidence-act#chunk-4]."

    result = _append_library_citations(answer, [first, second])

    assert "[source:evidence-act#chunk-4] Constitution" not in result
    assert "[source:constitution#chunk-7] Constitution · Article 12" in result
