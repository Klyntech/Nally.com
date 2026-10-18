"""CLI and helpers to ingest study documents into the library."""
from __future__ import annotations

import argparse
from pathlib import Path

from nally.library.store import LibraryStore


def read_source(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".markdown", ".text"}:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        return _read_pdf(path)
    raise ValueError(f"Unsupported file type: {suffix} (use .txt, .md, or text-layer .pdf)")


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "PDF support requires pypdf. Install with: pip install pypdf"
        ) from exc
    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    text = "\n\n".join(parts).strip()
    if not text:
        raise ValueError(
            f"No extractable text in {path.name}. Scan-only PDFs need OCR first."
        )
    return text


def ingest_file(
    path: Path,
    *,
    title: str | None = None,
    doc_type: str = "statute",
    jurisdiction: str = "",
    slug: str | None = None,
    embed: bool = True,
) -> dict:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    text = read_source(path)
    store = LibraryStore()
    return store.ingest_text(
        title=title or path.stem.replace("_", " ").replace("-", " "),
        text=text,
        doc_type=doc_type,
        jurisdiction=jurisdiction,
        source_path=str(path),
        slug=slug,
        embed=embed,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest a document into Nally library")
    parser.add_argument("path", type=Path, help="Path to .txt/.md/.pdf")
    parser.add_argument("--title", default=None)
    parser.add_argument("--type", dest="doc_type", default="statute",
                        help="statute | case | notes | other")
    parser.add_argument("--jurisdiction", default="")
    parser.add_argument("--slug", default=None)
    parser.add_argument("--no-embed", action="store_true",
                        help="Skip NVIDIA embeddings (FTS only)")
    args = parser.parse_args(argv)

    result = ingest_file(
        args.path,
        title=args.title,
        doc_type=args.doc_type,
        jurisdiction=args.jurisdiction,
        slug=args.slug,
        embed=not args.no_embed,
    )
    print(
        f"Ingested id={result['document_id']} slug={result['slug']} "
        f"chunks={result['chunks']} embedded={result['embedded']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
