from unittest.mock import MagicMock, call, patch

from nally.tools import web


def _client_context():
    client = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = client
    context.__exit__.return_value = False
    return context


def test_web_search_falls_back_in_provider_order_after_error_and_empty_results():
    context = _client_context()
    with (
        patch.object(web.httpx, "Client", return_value=context),
        patch.object(web, "TAVILY_API_KEY", "tavily-key"),
        patch.object(web, "BRAVE_SEARCH_API_KEY", "brave-key"),
        patch.object(web, "_search_tavily", side_effect=TimeoutError),
        patch.object(web, "_search_brave", return_value=[]) as brave,
        patch.object(
            web,
            "_search_duckduckgo",
            return_value=[("Example", "https://example.com", "A result")],
        ) as duckduckgo,
    ):
        result = web.web_search.invoke({"query": "test query", "max_results": 4})

    assert "https://example.com" in result
    brave.assert_called_once_with(context.__enter__.return_value, "test query", 4)
    duckduckgo.assert_called_once_with(context.__enter__.return_value, "test query", 4)


def test_web_search_stops_at_first_provider_with_results():
    context = _client_context()
    with (
        patch.object(web.httpx, "Client", return_value=context),
        patch.object(web, "_search_tavily", return_value=[("Tavily", "https://tavily.test", "")]) as tavily,
        patch.object(web, "_search_brave") as brave,
        patch.object(web, "_search_duckduckgo") as duckduckgo,
    ):
        result = web.web_search.invoke({"query": "test query"})

    assert "https://tavily.test" in result
    tavily.assert_called_once()
    brave.assert_not_called()
    duckduckgo.assert_not_called()


def test_web_search_returns_clear_error_when_all_providers_fail():
    context = _client_context()
    with (
        patch.object(web.httpx, "Client", return_value=context),
        patch.object(web, "_search_tavily", side_effect=TimeoutError),
        patch.object(web, "_search_brave", side_effect=ValueError),
        patch.object(web, "_search_duckduckgo", side_effect=RuntimeError),
    ):
        result = web.web_search.invoke({"query": "test query"})

    assert result.startswith("Error: all web search providers failed")
    assert "Tavily: TimeoutError" in result
    assert "Brave Search: ValueError" in result
    assert "DuckDuckGo: RuntimeError" in result


def test_web_search_reports_no_results_when_providers_are_empty():
    context = _client_context()
    with (
        patch.object(web.httpx, "Client", return_value=context),
        patch.object(web, "_search_tavily", return_value=[]),
        patch.object(web, "_search_brave", return_value=[]),
        patch.object(web, "_search_duckduckgo", return_value=[]),
    ):
        result = web.web_search.invoke({"query": "test query"})

    assert result == "No results for: test query"
