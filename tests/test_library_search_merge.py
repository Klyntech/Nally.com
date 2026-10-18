from nally.library.store import SearchHit, _cosine


def test_cosine_identical():
    v = [0.1, 0.2, 0.3]
    assert abs(_cosine(v, v) - 1.0) < 1e-6


def test_cosine_orthogonal():
    assert abs(_cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9


def test_search_hit_fields():
    h = SearchHit(
        document_id=1,
        document_title="Evidence Act",
        document_slug="evidence-act",
        section_label="Section 1",
        content="Short title",
        score=0.9,
        method="vector",
    )
    assert h.document_slug == "evidence-act"
