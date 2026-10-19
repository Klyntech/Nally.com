"""Split study documents into retrieval-friendly chunks."""
from __future__ import annotations

import re
from dataclasses import dataclass

# Statute-style headings: Section 1, s. 12, Article 15, Cap. 1, PART II
_SECTION_RE = re.compile(
    r"(?im)^(?:"
    r"(?:section|sec\.?|s\.)\s*\d+[A-Za-z]?"
    r"|(?:article|art\.)\s*\d+[A-Za-z]?"
    r"|(?:chapter|chap\.?|ch\.)\s*\d+[A-Za-z]?"
    r"|(?:part|schedule)\s+[IVXLC\d]+"
    r"|(?:regulation|reg\.)\s*\d+"
    r")\b.*$"
)


@dataclass
class Chunk:
    section_label: str
    text: str
    ordinal: int


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_document(text: str, *, max_chars: int = 1800, overlap: int = 120) -> list[Chunk]:
    """Prefer section boundaries; fall back to sliding windows."""
    text = _normalize(text)
    if not text:
        return []

    matches = list(_SECTION_RE.finditer(text))
    if len(matches) >= 2:
        chunks: list[Chunk] = []
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end].strip()
            if not body:
                continue
            label = match.group(0).strip()[:200]
            if len(body) <= max_chars:
                chunks.append(Chunk(section_label=label, text=body, ordinal=len(chunks)))
            else:
                for piece in _window(body, max_chars=max_chars, overlap=overlap):
                    chunks.append(
                        Chunk(section_label=label, text=piece, ordinal=len(chunks))
                    )
        if chunks:
            return chunks

    return [
        Chunk(section_label=f"chunk-{i+1}", text=piece, ordinal=i)
        for i, piece in enumerate(_window(text, max_chars=max_chars, overlap=overlap))
    ]


def _window(text: str, *, max_chars: int, overlap: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            # Prefer breaking on paragraph or sentence.
            cut = text.rfind("\n\n", start, end)
            if cut < start + max_chars // 3:
                cut = text.rfind(". ", start, end)
            if cut >= start + max_chars // 3:
                end = cut + 1
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return pieces
