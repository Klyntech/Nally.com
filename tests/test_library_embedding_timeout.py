"""Interactive library queries must not inherit the slow ingestion retry policy."""
from __future__ import annotations

import pytest

from nally.library import embeddings


def test_embed_query_uses_short_single_attempt(monkeypatch) -> None:
    captured = {}

    def fake_embed_texts(texts, **kwargs):
        captured["texts"] = texts
        captured.update(kwargs)
        return [[0.1, 0.2]]

    monkeypatch.setattr(embeddings, "embed_texts", fake_embed_texts)

    assert embeddings.embed_query("child protection") == [0.1, 0.2]
    assert captured["texts"] == ["child protection"]
    assert captured["input_type"] == "query"
    assert captured["timeout_s"] == 8.0
    assert captured["max_retries"] == 0


def test_embed_query_propagates_provider_failure_for_fts_fallback(monkeypatch) -> None:
    def fail_embed_texts(texts, **kwargs):
        raise embeddings.EmbeddingError("provider timed out")

    monkeypatch.setattr(embeddings, "embed_texts", fail_embed_texts)

    with pytest.raises(embeddings.EmbeddingError, match="provider timed out"):
        embeddings.embed_query("humanitarian affairs")
