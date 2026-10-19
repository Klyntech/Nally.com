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
            f"[source:{h.document_slug}#chunk-{h.ordinal}] "
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
        blocks.append(
            f"{r['title']} · {r['section_label']} "
            f"[source:{r['slug']}#chunk-{r['ordinal']}]\n{body}"
        )
    return "\n\n".join(blocks)


@tool
def library_rename(
    current_slug: str,
    new_title: str = "",
    new_slug: str = "",
    jurisdiction: str = "",
    doc_type: str = "",
) -> str:
    """Rename a library document or change its slug/jurisdiction/type without re-ingesting.

    current_slug identifies the existing document (from library_list).
    Provide any of new_title, new_slug, jurisdiction, doc_type to update those fields.
    """
    current_slug = (current_slug or "").strip()
    if not current_slug:
        return "Error: current_slug is required (use library_list first)"
    if not any([(new_title or "").strip(), (new_slug or "").strip(), jurisdiction, doc_type]):
        return "Error: provide at least one of new_title, new_slug, jurisdiction, doc_type"
    try:
        result = get_library_store().rename_document(
            current_slug,
            new_title=new_title.strip() or None,
            new_slug=new_slug.strip() or None,
            jurisdiction=jurisdiction if jurisdiction != "" else None,
            doc_type=doc_type.strip() or None,
        )
    except Exception as e:
        return f"Error: rename failed: {e}"
    return (
        f"Renamed library document.\n"
        f"previous_slug={result['previous_slug']}\n"
        f"slug={result['slug']}\n"
        f"title={result['title']}\n"
        f"type={result['doc_type']}\n"
        f"jurisdiction={result['jurisdiction'] or '(none)'}"
    )
