from unittest.mock import patch

import pytest

from nally.agent import graph


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Search for ABSU Admission", "ABSU Admission"),
        ("Search the Web for Flex X Cop", "Flex X Cop"),
        ('Please search the web for "ABSU admission".', "ABSU admission"),
        ("look up Lagos weather", "Lagos weather"),
        ("find online Nally repository", "Nally repository"),
    ],
)
def test_direct_search_query_extracts_explicit_queries(message, expected):
    assert graph._direct_search_query(message) == expected


@pytest.mark.parametrize(
    "message",
    [
        "",
        "Can you help me understand admissions?",
        "I searched the web yesterday",
        "Search",
        "Search for",
        "Search the web for",
        "Please search for",
    ],
)
def test_direct_search_query_does_not_capture_normal_chat(message):
    assert graph._direct_search_query(message) is None


def test_explicit_search_bypasses_agent_graph():
    with (
        patch.object(graph.web_search, "invoke", return_value="1. Example result") as search,
        patch.object(graph, "get_graph", side_effect=AssertionError("LLM graph must not run")),
        patch.object(graph, "get_memory_store") as memory_store,
    ):
        result = graph.run_agent("Search for ABSU Admission")

    assert result == "1. Example result"
    search.assert_called_once_with({"query": "ABSU Admission", "max_results": 4})
