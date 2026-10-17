from nally.telegram.Telegram_Render import render_telegram_html, split_telegram_html


def test_bold_markdown_becomes_telegram_html():
    rendered = render_telegram_html("This is **bold** text.")
    assert "<strong>bold</strong>" in rendered
    assert "**bold**" not in rendered


def test_markdown_table_becomes_aligned_preformatted_text():
    rendered = render_telegram_html(
        "| Name | Status |\n"
        "| --- | --- |\n"
        "| Nally | Ready |\n"
        "| Worker | Pending |"
    )
    assert "<pre>" in rendered
    assert "Name" in rendered and "Status" in rendered
    assert "Nally" in rendered and "Pending" in rendered
    assert "<table>" not in rendered


def test_raw_html_is_not_trusted():
    rendered = render_telegram_html("<script>alert(1)</script>\n\n**safe**")
    assert "<script>" not in rendered
    assert "<strong>safe</strong>" in rendered


def test_split_keeps_each_chunk_within_limit_and_balances_basic_tags():
    rendered = "<b>" + ("word " * 40) + "</b>"
    chunks = split_telegram_html(rendered, limit=48)
    assert len(chunks) > 1
    assert all(len(chunk) <= 48 for chunk in chunks)
    assert all(chunk.count("<b>") == chunk.count("</b>") for chunk in chunks)


def test_empty_input():
    assert render_telegram_html("") == ""
    assert split_telegram_html("") == []
