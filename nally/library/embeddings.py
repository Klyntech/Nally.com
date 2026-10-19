"""NVIDIA cloud embeddings for library retrieval."""
from __future__ import annotations

import logging
from typing import Literal

import httpx

from nally.config import (
    NVIDIA_EMBED_API_KEY,
    NVIDIA_EMBED_BASE_URL,
    NVIDIA_EMBED_DIM,
    NVIDIA_EMBED_MODEL,
)

logger = logging.getLogger("nally")

InputType = Literal["query", "passage"]


class EmbeddingError(RuntimeError):
    """Raised when the embedding provider fails."""


def embed_texts(
    texts: list[str],
    *,
    input_type: InputType = "passage",
    timeout_s: float = 60.0,
    max_retries: int = 2,
) -> list[list[float]]:
    """Embed one or more strings via NVIDIA /v1/embeddings."""
    if not texts:
        return []
    if not NVIDIA_EMBED_API_KEY:
        raise EmbeddingError(
            "NVIDIA_EMBED_API_KEY (or NVIDIA_API_KEY / NVIDIA_NIM_API_KEY) is not set"
        )

    cleaned = [(t or "").strip() or " " for t in texts]
    payload = {
        "model": NVIDIA_EMBED_MODEL,
        "input": cleaned,
        "input_type": input_type,
        "encoding_format": "float",
    }
    headers = {
        "Authorization": f"Bearer {NVIDIA_EMBED_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    url = NVIDIA_EMBED_BASE_URL.rstrip("/") + "/embeddings"

    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            with httpx.Client(timeout=timeout_s) as client:
                resp = client.post(url, json=payload, headers=headers)
            if resp.status_code >= 400:
                raise EmbeddingError(
                    f"NVIDIA embeddings HTTP {resp.status_code}: {resp.text[:300]}"
                )
            data = resp.json()
            items = data.get("data") or []
            if len(items) != len(cleaned):
                raise EmbeddingError(
                    f"Expected {len(cleaned)} embeddings, got {len(items)}"
                )
            vectors: list[list[float]] = []
            for item in sorted(items, key=lambda x: x.get("index", 0)):
                emb = item.get("embedding") or []
                if not emb:
                    raise EmbeddingError("Empty embedding vector in response")
                vectors.append([float(x) for x in emb])
            if vectors and len(vectors[0]) != NVIDIA_EMBED_DIM:
                logger.warning(
                    "Embedding dim %s differs from configured NVIDIA_EMBED_DIM=%s",
                    len(vectors[0]),
                    NVIDIA_EMBED_DIM,
                )
            return vectors
        except Exception as exc:
            last_err = exc
            logger.warning(
                "embed attempt %s/%s failed: %s",
                attempt + 1,
                max_retries + 1,
                type(exc).__name__,
            )
    raise EmbeddingError(str(last_err) if last_err else "embedding failed")


def embed_query(text: str) -> list[float]:
    return embed_texts([text], input_type="query")[0]


def embed_passages(texts: list[str], *, batch_size: int = 16) -> list[list[float]]:
    """Embed passages in batches (ingest path)."""
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        chunk = texts[i : i + batch_size]
        out.extend(embed_texts(chunk, input_type="passage"))
    return out
