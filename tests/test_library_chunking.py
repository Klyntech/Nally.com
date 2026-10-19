from nally.library.chunking import chunk_document


def test_section_aware_chunking():
    text = """
Section 1. Short title
This Act may be cited as the Evidence Act.

Section 2. Interpretation
In this Act, unless the context otherwise requires, court means a court of competent jurisdiction.

Section 3. Application
This Act applies to all judicial proceedings in or before any court.
""".strip()
    chunks = chunk_document(text)
    assert len(chunks) >= 3
    assert any("Section 1" in c.section_label for c in chunks)
    assert any("Interpretation" in c.text for c in chunks)


def test_fallback_window_for_plain_notes():
    text = "Paragraph one about burden of proof. " * 80
    chunks = chunk_document(text, max_chars=200, overlap=20)
    assert len(chunks) > 1
    assert all(c.text for c in chunks)
