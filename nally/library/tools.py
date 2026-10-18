"""Agent tools for the personal law / study library."""
from __future__ import annotations

from langchain_core.tools import tool

from nally.library.store import get_library_store


@tool
def library_list(limit: int = 30) -> str:
    """List documents in the personal study library (statutes, cases, notes)."""
    try:
        docs = get_library_store().list_documents(limit=limit)
    except Exception as e:
        return f"Error: library unavailable: {e}"
    if not docs:
        return "Library is empty. Ingest documents with: python -m nally.library.ingest <file>"
    lines = []
    for d in docs:
        jur = f" [{d['jurisdiction']}]" if d.get("jurisdiction") else ""
        lines.append(
            f"- {d['title']}{jur} (slug={d['slug']}, type={d['doc_type']}, chunks={d['chunk_count']})"
        )
    return "\n".join(lines)


@tool
def library_search(query: str, limit: int = 6, document_slug: str = "") -> str:
    """Search the personal study library (Constitution, Evidence Act, cases, notes).

    Prefer this over web_search for questions about materials the user has ingested.
    Returns ranked excerpts with document title and section labels for citation.
    """
    query = (query or "").strip()
    if not query:
        return "Error: empty query"
    try:
        hits = get_library_store().search(
            query,
            limit=limit,
            document_slug=document_slug.strip() or None,
        )
    except Exception as e:
        return f"Error: library search failed: {e}"
    if not hits:
        return (
            "No matching passages in the library. "
            "Say so to the user; only use web_search if they want external sources."
        )
    blocks = []
    for i, h in enumerate(hits, 1):
        excerpt = h.content.strip()
        if len(excerpt) > 1200:
            excerpt = excerpt[:1200] + "…"
        blocks.append(
            f"[{i}] {h.document_title} · {h.section_label or 'passage'} "
            f"(score={h.score:.3f}, via={h.method})\n{excerpt}"
        )
    return "\n\n".join(blocks)


@tool
def library_get(document_slug: str, section_query: str = "", limit: int = 3) -> str:
    """Fetch passages from a specific library document by slug, optionally filtered by section text."""
    document_slug = (document_slug or "").strip()
    if not document_slug:
        return "Error: document_slug is required (use library_list first)"
    try:
        rows = get_library_store().get_chunk(
            document_slug=document_slug,
            section_query=section_query.strip() or None,
            limit=limit,
        )
    except Exception as e:
        return f"Error: library get failed: {e}"
    if not rows:
        return f"No passages found for slug={document_slug!r} section={section_query!r}"
    blocks = []
    for r in rows:
        body = r["content"]
        if len(body) > 2000:
            body = body[:2000] + "…"
        blocks.append(f"{r['title']} · {r['section_label']}\n{body}")
    return "\n\n".join(blocks)
