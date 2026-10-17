"""Markdown-to-Telegram HTML rendering helpers."""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

from markdown_it import MarkdownIt

_MARKDOWN = MarkdownIt("commonmark", {"html": False, "breaks": True})


def _cells(line: str) -> list[str]:
    line = line.strip().strip("|")
    return [part.strip().replace(r"\|", "|") for part in re.split(r"(?<!\\)\|", line)]


def _is_separator(line: str) -> bool:
    cells = _cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in cells)


def _table_text(lines: list[str]) -> str:
    rows = [_cells(line) for line in lines]
    headers = rows[0]
    body = rows[2:] if len(rows) > 1 and _is_separator(lines[1]) else rows[1:]
    count = max([len(headers), *(len(row) for row in body)])
    rows = [headers + [""] * (count - len(headers))]
    rows += [row + [""] * (count - len(row)) for row in body]
    widths = [min(32, max(3, *(len(row[i]) for row in rows))) for i in range(count)]

    def fmt(row: list[str]) -> str:
        cells = []
        for i, value in enumerate(row):
            value = re.sub(r"\s+", " ", value)
            if len(value) > widths[i]:
                value = value[:widths[i] - 1] + "…"
            cells.append(value.ljust(widths[i]))
        return "  ".join(cells).rstrip()

    return "\n".join([fmt(rows[0]), "  ".join("-" * w for w in widths), *(fmt(r) for r in rows[1:])])


def _tables_to_fences(text: str) -> str:
    lines = text.splitlines()
    result: list[str] = []
    i = 0
    in_fence = False
    while i < len(lines):
        if lines[i].lstrip().startswith("~~~"):
            in_fence = not in_fence
            result.append(lines[i])
            i += 1
            continue
        if not in_fence and i + 1 < len(lines) and "|" in lines[i] and _is_separator(lines[i + 1]):
            table = [lines[i], lines[i + 1]]
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                table.append(lines[i])
                i += 1
            result.extend(["~~~text", _table_text(table), "~~~"])
        else:
            result.append(lines[i])
            i += 1
    return "\n".join(result)


class _TelegramHTML(HTMLParser):
    allowed = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "code", "pre", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.stack: list[str] = []
        self.pre_depth = 0

    def newline(self, count: int = 1) -> None:
        current = "".join(self.parts)
        trailing = len(current) - len(current.rstrip("\n"))
        if trailing < count:
            self.parts.append("\n" * (count - trailing))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        if tag in {"p", "div"}:
            self.newline()
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.newline()
            self.parts.append("<b>")
            self.stack.append("__heading__")
        elif tag in {"ul", "ol"}:
            self.newline()
        elif tag == "li":
            self.newline()
            self.parts.append("• ")
        elif tag == "br":
            self.newline()
        elif tag == "hr":
            self.newline()
            self.parts.append("────────")
            self.newline()
        elif tag == "a":
            href = attrs_map.get("href") or ""
            if urlparse(href).scheme in {"http", "https", "mailto", "tg"}:
                self.parts.append('<a href="' + html.escape(href, quote=True) + '">')
                self.stack.append("a")
        elif tag in self.allowed:
            self.parts.append("<" + tag + ">")
            self.stack.append(tag)
            if tag == "pre":
                self.pre_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "div", "li", "ul", "ol"}:
            self.newline()
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            if "__heading__" in self.stack:
                self.stack.remove("__heading__")
                self.parts.append("</b>")
            self.newline()
            return
        closing = "a" if tag == "a" else tag
        if closing in self.stack:
            index = len(self.stack) - 1 - self.stack[::-1].index(closing)
            for item in reversed(self.stack[index:]):
                if item in self.allowed or item == "a":
                    self.parts.append("</" + item + ">")
                    if item == "pre":
                        self.pre_depth = max(0, self.pre_depth - 1)
            del self.stack[index:]

    def handle_data(self, data: str) -> None:
        self.parts.append(html.escape(data, quote=False) if self.pre_depth else data)

    def handle_entityref(self, name: str) -> None:
        self.parts.append("&" + name + ";")

    def handle_charref(self, name: str) -> None:
        self.parts.append("&#" + name + ";")

    def finish(self) -> str:
        while self.stack:
            tag = self.stack.pop()
            if tag in self.allowed or tag == "a":
                self.parts.append("</" + tag + ">")
        value = re.sub(r"[ \t]+\n", "\n", "".join(self.parts))
        return re.sub(r"\n{3,}", "\n\n", value).strip()


def render_telegram_html(text: str) -> str:
    """Render Markdown as Telegram-safe HTML, keeping tables readable."""
    if not text:
        return ""
    parser = _TelegramHTML()
    parser.feed(_MARKDOWN.render(_tables_to_fences(text)))
    parser.close()
    return parser.finish()


def split_telegram_html(text: str, limit: int = 4000) -> list[str]:
    """Split HTML into Telegram-sized chunks while closing/reopening formatting tags."""
    if limit < 32:
        raise ValueError("limit must be at least 32")
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    stack: list[tuple[str, str]] = []
    tokens = re.findall(r"<[^>]+>|[^<]+", text)
    for token in tokens:
        if token.startswith("</"):
            name = token[2:-1].split()[0]
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == name:
                    stack.pop(i)
                    break
        elif token.startswith("<"):
            match = re.match(r"<([a-zA-Z]+)(?:\s|>)", token)
            if match and match.group(1) in _TelegramHTML.allowed | {"a"}:
                stack.append((match.group(1), token))
        closing = "".join("</" + name + ">" for name, _ in reversed(stack))
        if current and len(current) + len(token) + len(closing) > limit:
            chunks.append(current + closing)
            current = "".join(opening for _, opening in stack)
        current += token
    if current:
        chunks.append(current)
    return chunks
