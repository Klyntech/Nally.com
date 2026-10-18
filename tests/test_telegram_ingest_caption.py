from nally.telegram.bot import _parse_ingest_caption


def test_caption_defaults_from_filename():
    meta = _parse_ingest_caption(None, "Evidence_Act.pdf")
    assert meta["title"] == "Evidence Act"
    assert meta["doc_type"] == "statute"


def test_caption_metadata_tags():
    meta = _parse_ingest_caption(
        "Evidence Act 2011 type:statute jurisdiction:Nigeria slug:evidence-act",
        "file.pdf",
    )
    assert meta["title"] == "Evidence Act 2011"
    assert meta["doc_type"] == "statute"
    assert meta["jurisdiction"] == "Nigeria"
    assert meta["slug"] == "evidence-act"
