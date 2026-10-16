"""web_search + fetch — HTTP tools (no API key required)."""
from __future__ import annotations

import re
from html import unescape
from urllib.parse import quote_plus, urlparse

import httpx
from langchain_core.tools import tool

from nally.config import MAX_TOOL_OUTPUT

_TIMEOUT = 20.0
_HEADERS = {
    "User-Agent": "NallyBot/0.1 (+https://github.com/Klyntech/Nally.com)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


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


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web for current information. Returns titles, URLs, and snippets.
    Use for news, facts, docs — not for private/local data.
    """
    query = (query or "").strip()
    if not query:
        return "Error: empty query"
    max_results = max(1, min(int(max_results or 5), 8))

    url = "https://html.duckduckgo.com/html/"
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS) as client:
            r = client.post(url, data={"q": query})
            r.raise_for_status()
            html = r.text
    except Exception as e:
        return f"Error: search failed: {e}"

    # DDG HTML result blocks
    results = []
    # result links
    for m in re.finditer(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</(?:a|td|div)',
        html,
        re.I | re.S,
    ):
        href, title, snippet = m.group(1), m.group(2), m.group(3)
        title = _strip_html(title)
        snippet = _strip_html(snippet)
        # unwrap DDG redirect
        if "uddg=" in href:
            from urllib.parse import parse_qs, urlparse as up

            qs = parse_qs(up(href).query)
            href = qs.get("uddg", [href])[0]
        results.append((title, href, snippet))
        if len(results) >= max_results:
            break

    if not results:
        # fallback: simpler pattern
        for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.I | re.S):
            href, title = m.group(1), _strip_html(m.group(2))
            if "uddg=" in href:
                from urllib.parse import parse_qs, urlparse as up

                qs = parse_qs(up(href).query)
                href = qs.get("uddg", [href])[0]
            results.append((title, href, ""))
            if len(results) >= max_results:
                break

    if not results:
        return f"No results for: {query}"

    lines = []
    for i, (title, href, snippet) in enumerate(results, 1):
        lines.append(f"{i}. {title}\n   {href}")
        if snippet:
            lines.append(f"   {snippet[:240]}")
    out = "\n".join(lines)
    if len(out) > MAX_TOOL_OUTPUT:
        out = out[:MAX_TOOL_OUTPUT] + "\n...[truncated]"
    return out


@tool
def fetch(url: str) -> str:
    """Fetch a URL and return readable text content (HTML stripped).
    Use after web_search when you need the full page.
    """
    url = (url or "").strip()
    if not url:
        return "Error: empty url"
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "Error: only http/https URLs allowed"

    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS) as client:
            r = client.get(url)
            r.raise_for_status()
            ctype = (r.headers.get("content-type") or "").lower()
            raw = r.text
    except Exception as e:
        return f"Error: fetch failed: {e}"

    if "html" in ctype or raw.lstrip().startswith("<!"):
        text = _strip_html(raw)
    else:
        text = raw

    if len(text) > MAX_TOOL_OUTPUT:
        text = text[:MAX_TOOL_OUTPUT] + "\n...[truncated]"
    return text or "(empty page)"
