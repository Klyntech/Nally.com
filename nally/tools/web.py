"""Web search and URL-fetch tools for Nally."""
from __future__ import annotations

import logging
import re
import time
from html import unescape
from urllib.parse import parse_qs, urlparse

import httpx
from langchain_core.tools import tool

from nally.config import BRAVE_SEARCH_API_KEY, MAX_TOOL_OUTPUT, TAVILY_API_KEY

_TIMEOUT = 20.0
_HEADERS = {
    "User-Agent": "NallyBot/0.1 (+https://github.com/Klyntech/Nally.com)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_LOG = logging.getLogger(__name__)


def _strip_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript|svg).*?>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<!--.*?-->", " ", html)
    html = re.sub(r"(?is)<br\s*/?>", "\n", html)
    html = re.sub(r"(?is)</p>", "\n\n", html)
    html = re.sub(r"(?is)<[^>]+>", " ", html)
    text = unescape(html)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _search_tavily(client: httpx.Client, query: str, limit: int) -> list[tuple[str, str, str]]:
    if not TAVILY_API_KEY:
        return []
    response = client.post(
        "https://api.tavily.com/search",
        json={
            "api_key": TAVILY_API_KEY,
            "query": query,
            "max_results": limit,
            "search_depth": "basic",
            "include_answer": False,
        },
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    payload = response.json()
    return [
        (
            str(item.get("title") or item.get("url") or "Untitled"),
            str(item.get("url") or ""),
            str(item.get("content") or "")[:240],
        )
        for item in payload.get("results", [])
        if item.get("url")
    ][:limit]


def _search_brave(client: httpx.Client, query: str, limit: int) -> list[tuple[str, str, str]]:
    if not BRAVE_SEARCH_API_KEY:
        return []
    response = client.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": limit},
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": BRAVE_SEARCH_API_KEY,
        },
    )
    response.raise_for_status()
    payload = response.json()
    web_results = payload.get("web", {}).get("results", [])
    return [
        (
            str(item.get("title") or item.get("url") or "Untitled"),
            str(item.get("url") or ""),
            str(item.get("description") or "")[:240],
        )
        for item in web_results
        if item.get("url")
    ][:limit]


def _search_duckduckgo(client: httpx.Client, query: str, limit: int) -> list[tuple[str, str, str]]:
    response = client.post("https://html.duckduckgo.com/html/", data={"q": query})
    response.raise_for_status()
    html = response.text
    results: list[tuple[str, str, str]] = []

    for match in re.finditer(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)',
        html,
        re.I | re.S,
    ):
        href, title, snippet = match.groups()
        if "uddg=" in href:
            href = parse_qs(urlparse(href).query).get("uddg", [href])[0]
        results.append((_strip_html(title), href, _strip_html(snippet)[:240]))
        if len(results) >= limit:
            break

    if not results:
        for match in re.finditer(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            html,
            re.I | re.S,
        ):
            href, title = match.groups()
            if "uddg=" in href:
                href = parse_qs(urlparse(href).query).get("uddg", [href])[0]
            results.append((_strip_html(title), href, ""))
            if len(results) >= limit:
                break
    return results


def _format_results(results: list[tuple[str, str, str]], query: str) -> str:
    if not results:
        return f"No results for: {query}"
    lines = []
    for index, (title, url, snippet) in enumerate(results, 1):
        lines.append(f"{index}. {title}\n   {url}")
        if snippet:
            lines.append(f"   {snippet}")
    output = "\n".join(lines)
    if len(output) > MAX_TOOL_OUTPUT:
        output = output[:MAX_TOOL_OUTPUT] + "\n...[truncated]"
    return output


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web using Tavily, then Brave Search, then DuckDuckGo.

    Returns titles, URLs, and snippets. Use for current information, news, and
    documentation, not private or local data.
    """
    query = (query or "").strip()
    if not query:
        return "Error: empty query"
    try:
        limit = max(1, min(int(max_results or 5), 8))
    except (TypeError, ValueError):
        limit = 5

    providers = (
        ("Tavily", _search_tavily),
        ("Brave Search", _search_brave),
        ("DuckDuckGo", _search_duckduckgo),
    )
    failures = []
    per_provider_timeout = 8.0
    total_timeout = 18.0
    deadline = time.monotonic() + total_timeout
    search_timeout = httpx.Timeout(per_provider_timeout, connect=3.0)
    with httpx.Client(timeout=search_timeout, follow_redirects=True, headers=_HEADERS) as client:
        for provider_name, search_fn in providers:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failures.append("overall search deadline exceeded")
                break
            timeout = min(per_provider_timeout, remaining)
            client.timeout = httpx.Timeout(timeout, connect=min(3.0, timeout))
            try:
                results = search_fn(client, query, limit)
                if results:
                    if failures:
                        _LOG.warning(
                            "web_search used %s after earlier provider failure(s): %s",
                            provider_name,
                            "; ".join(failures),
                        )
                    return _format_results(results, query)
                _LOG.info("web_search provider %s returned no usable results", provider_name)
            except Exception as exc:
                failures.append(f"{provider_name}: {type(exc).__name__}")
                _LOG.warning("web_search provider %s failed: %s", provider_name, exc)

    if failures:
        return f"Error: all web search providers failed ({'; '.join(failures)})"
    return f"No results for: {query}"


@tool
def fetch(url: str) -> str:
    """Fetch a URL and return readable text content (HTML stripped).

    Use after web_search when you need the full page.
    """
    url = (url or "").strip()
    if not url:
        return "Error: empty url"
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "Error: only valid http/https URLs allowed"

    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS) as client:
            response = client.get(url)
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").lower()
            raw = response.text
    except httpx.HTTPError as exc:
        _LOG.warning("fetch failed for %s: %s", url, exc)
        return f"Error: fetch failed: {type(exc).__name__}"

    text = _strip_html(raw) if "html" in content_type or raw.lstrip().startswith("<!") else raw
    if len(text) > MAX_TOOL_OUTPUT:
        text = text[:MAX_TOOL_OUTPUT] + "\n...[truncated]"
    return text or "(empty page)"
