"""Postgres-backed document library with FTS and embedding similarity."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

from nally.config import DATABASE_URL
from nally.core.logging import logger
from nally.library.chunking import chunk_document
from nally.library.embeddings import EmbeddingError, embed_passages, embed_query

_SCHEMA = """
CREATE TABLE IF NOT EXISTS library_documents (
    id BIGSERIAL PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    doc_type TEXT NOT NULL DEFAULT 'statute',
    jurisdiction TEXT NOT NULL DEFAULT '',
    source_path TEXT NOT NULL DEFAULT '',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS library_chunks (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES library_documents(id) ON DELETE CASCADE,
    ordinal INT NOT NULL,
    section_label TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    embedding JSONB,
    tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(section_label, '') || ' ' || coalesce(content, ''))
    ) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(document_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_library_chunks_document
    ON library_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_library_chunks_tsv
    ON library_chunks USING GIN (tsv);
"""


@dataclass
class SearchHit:
    document_id: int
    document_title: str
    document_slug: str
    section_label: str
    content: str
    score: float
    method: str


def _slugify(value: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return (s or "document")[:80]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class LibraryStore:
    def __init__(self, database_url: str | None = None):
        self.url = database_url or DATABASE_URL
        if not self.url:
            raise RuntimeError("DATABASE_URL is required for the library")
        self._ensure_schema()

    def _conn(self):
        import psycopg

        return psycopg.connect(self.url)

    def _ensure_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(_SCHEMA)
            conn.commit()
        logger.info("Library schema ready")

    def list_documents(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT d.id, d.slug, d.title, d.doc_type, d.jurisdiction,
                       COUNT(c.id) AS chunk_count, d.updated_at
                FROM library_documents d
                LEFT JOIN library_chunks c ON c.document_id = d.id
                GROUP BY d.id
                ORDER BY d.updated_at DESC
                LIMIT %s
                """,
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [
            {
                "id": r[0],
                "slug": r[1],
                "title": r[2],
                "doc_type": r[3],
                "jurisdiction": r[4],
                "chunk_count": r[5],
                "updated_at": str(r[6]),
            }
            for r in rows
        ]

    def get_chunk(
        self,
        *,
        document_slug: str | None = None,
        document_id: int | None = None,
        section_query: str | None = None,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        if not document_slug and document_id is None:
            return []
        clauses = []
        params: list[Any] = []
        if document_id is not None:
            clauses.append("d.id = %s")
            params.append(document_id)
        if document_slug:
            clauses.append("d.slug = %s")
            params.append(document_slug)
        where = " AND ".join(clauses)
        if section_query:
            sql = f"""
                SELECT d.title, d.slug, c.section_label, c.content, c.ordinal
                FROM library_chunks c
                JOIN library_documents d ON d.id = c.document_id
                WHERE {where}
                  AND (c.section_label ILIKE %s OR c.content ILIKE %s)
                ORDER BY c.ordinal
                LIMIT %s
            """
            like = f"%{section_query.strip()}%"
            params.extend([like, like, max(1, min(limit, 20))])
        else:
            sql = f"""
                SELECT d.title, d.slug, c.section_label, c.content, c.ordinal
                FROM library_chunks c
                JOIN library_documents d ON d.id = c.document_id
                WHERE {where}
                ORDER BY c.ordinal
                LIMIT %s
            """
            params.append(max(1, min(limit, 20)))
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "title": r[0],
                "slug": r[1],
                "section_label": r[2],
                "content": r[3],
                "ordinal": r[4],
            }
            for r in rows
        ]

    def ingest_text(
        self,
        *,
        title: str,
        text: str,
        doc_type: str = "statute",
        jurisdiction: str = "",
        source_path: str = "",
        slug: str | None = None,
        replace: bool = True,
        embed: bool = True,
    ) -> dict[str, Any]:
        slug = _slugify(slug or title)
        chunks = chunk_document(text)
        if not chunks:
            raise ValueError("No content to ingest")

        embeddings: list[list[float] | None]
        if embed:
            try:
                embeddings = embed_passages([c.text for c in chunks])  # type: ignore[assignment]
            except EmbeddingError as exc:
                logger.warning("Ingest continuing without embeddings: %s", exc)
                embeddings = [None] * len(chunks)
        else:
            embeddings = [None] * len(chunks)

        with self._conn() as conn:
            if replace:
                conn.execute("DELETE FROM library_documents WHERE slug = %s", (slug,))
            row = conn.execute(
                """
                INSERT INTO library_documents
                    (slug, title, doc_type, jurisdiction, source_path, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (slug) DO UPDATE SET
                    title = EXCLUDED.title,
                    doc_type = EXCLUDED.doc_type,
                    jurisdiction = EXCLUDED.jurisdiction,
                    source_path = EXCLUDED.source_path,
                    updated_at = NOW()
                RETURNING id
                """,
                (slug, title, doc_type, jurisdiction, source_path),
            ).fetchone()
            doc_id = int(row[0])
            conn.execute("DELETE FROM library_chunks WHERE document_id = %s", (doc_id,))
            for chunk, emb in zip(chunks, embeddings):
                conn.execute(
                    """
                    INSERT INTO library_chunks
                        (document_id, ordinal, section_label, content, embedding)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        doc_id,
                        chunk.ordinal,
                        chunk.section_label,
                        chunk.text,
                        json.dumps(emb) if emb is not None else None,
                    ),
                )
            conn.commit()

        embedded = sum(1 for e in embeddings if e is not None)
        return {
            "document_id": doc_id,
            "slug": slug,
            "title": title,
            "chunks": len(chunks),
            "embedded": embedded,
        }

    def search(
        self,
        query: str,
        *,
        limit: int = 6,
        document_slug: str | None = None,
    ) -> list[SearchHit]:
        query = (query or "").strip()
        if not query:
            return []

        fts_hits = self._search_fts(query, limit=limit * 2, document_slug=document_slug)
        vec_hits: list[SearchHit] = []
        try:
            qvec = embed_query(query)
            vec_hits = self._search_vectors(
                qvec, limit=limit * 2, document_slug=document_slug
            )
        except EmbeddingError as exc:
            logger.warning("Vector search unavailable: %s", exc)

        merged: dict[tuple[int, str, str], SearchHit] = {}
        for hit in fts_hits + vec_hits:
            key = (hit.document_id, hit.section_label, hit.content[:80])
            prev = merged.get(key)
            if prev is None or hit.score > prev.score:
                merged[key] = hit

        ranked = sorted(merged.values(), key=lambda h: h.score, reverse=True)
        return ranked[: max(1, min(limit, 20))]

    def _search_fts(
        self, query: str, *, limit: int, document_slug: str | None
    ) -> list[SearchHit]:
        slug_clause = ""
        if document_slug:
            slug_clause = "AND d.slug = %s"
            params: list[Any] = [query, query, document_slug, limit]
        else:
            params = [query, query, limit]
        sql = f"""
            SELECT d.id, d.title, d.slug, c.section_label, c.content,
                   ts_rank_cd(c.tsv, plainto_tsquery('english', %s)) AS rank
            FROM library_chunks c
            JOIN library_documents d ON d.id = c.document_id
            WHERE c.tsv @@ plainto_tsquery('english', %s)
            {slug_clause}
            ORDER BY rank DESC
            LIMIT %s
        """
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            SearchHit(
                document_id=int(r[0]),
                document_title=r[1],
                document_slug=r[2],
                section_label=r[3] or "",
                content=r[4],
                score=float(r[5] or 0) + 0.15,
                method="fts",
            )
            for r in rows
        ]

    def _search_vectors(
        self,
        query_vec: list[float],
        *,
        limit: int,
        document_slug: str | None,
    ) -> list[SearchHit]:
        params: list[Any] = []
        slug_clause = ""
        if document_slug:
            slug_clause = "AND d.slug = %s"
            params.append(document_slug)
        sql = f"""
            SELECT d.id, d.title, d.slug, c.section_label, c.content, c.embedding
            FROM library_chunks c
            JOIN library_documents d ON d.id = c.document_id
            WHERE c.embedding IS NOT NULL
            {slug_clause}
        """
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()

        scored: list[SearchHit] = []
        for r in rows:
            emb = r[5]
            if isinstance(emb, str):
                emb = json.loads(emb)
            if not isinstance(emb, list):
                continue
            score = _cosine(query_vec, [float(x) for x in emb])
            scored.append(
                SearchHit(
                    document_id=int(r[0]),
                    document_title=r[1],
                    document_slug=r[2],
                    section_label=r[3] or "",
                    content=r[4],
                    score=score,
                    method="vector",
                )
            )
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[: max(1, min(limit, 50))]


_store: LibraryStore | None = None


def get_library_store() -> LibraryStore:
    global _store
    if _store is None:
        _store = LibraryStore()
    return _store
