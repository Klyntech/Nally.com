"""Telegram bot — webhook (Render) or polling (local)."""
from __future__ import annotations

import asyncio
import re
import tempfile
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from nally.config import (
    LIBRARY_DEFAULT_JURISDICTION,
    LIBRARY_MAX_UPLOAD_MB,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_MODE,
    TELEGRAM_USER_ID,
    TELEGRAM_WEBHOOK_SECRET,
    WORKSPACE,
)
from nally.core.logging import logger
from nally.telegram.menus import (
    HOME_TEXT,
    help_screen,
    home_keyboard,
    mcp_screen,
    tools_screen,
)
from nally.telegram.rich import TelegramRichMessageError, TelegramRichTransport
from nally.telegram.telegram_renderer import (
    contains_markdown_table,
    render_telegram_html,
    split_telegram_html,
)

# Telegram Rich Message body limit is generous; keep a practical ceiling.
_RICH_MARKDOWN_LIMIT = 32768

_ALLOWED_DOC_SUFFIXES = {".pdf", ".txt", ".md", ".markdown", ".text"}
_CAPTION_TYPE_RE = re.compile(r"(?:^|\s)type:([a-zA-Z0-9_-]+)", re.I)
_CAPTION_JURISDICTION_RE = re.compile(r"(?:^|\s)jurisdiction:([\w\s.-]+?)(?=\s+type:|$)", re.I)
_CAPTION_SLUG_RE = re.compile(r"(?:^|\s)slug:([a-zA-Z0-9_-]+)", re.I)


def _allowed(user_id: int | None) -> bool:
    if not TELEGRAM_USER_ID:
        return True  # open if unset (dev)
    return user_id is not None and int(user_id) == int(TELEGRAM_USER_ID)


def _parse_ingest_caption(caption: str | None, filename: str) -> dict[str, str]:
    """Extract title / type / jurisdiction / slug from an optional caption."""
    caption = (caption or "").strip()
    doc_type = "statute"
    jurisdiction = LIBRARY_DEFAULT_JURISDICTION
    slug = ""
    title_parts = caption

    if caption:
        m = _CAPTION_TYPE_RE.search(caption)
        if m:
            doc_type = m.group(1).lower()
            title_parts = _CAPTION_TYPE_RE.sub("", title_parts)
        m = _CAPTION_JURISDICTION_RE.search(caption)
        if m:
            jurisdiction = m.group(1).strip()
            title_parts = _CAPTION_JURISDICTION_RE.sub("", title_parts)
        m = _CAPTION_SLUG_RE.search(caption)
        if m:
            slug = m.group(1).strip()
            title_parts = _CAPTION_SLUG_RE.sub("", title_parts)

    title = re.sub(r"\s+", " ", title_parts).strip(" -|")
    if not title:
        title = Path(filename).stem.replace("_", " ").replace("-", " ")
    return {
        "title": title,
        "doc_type": doc_type,
        "jurisdiction": jurisdiction,
        "slug": slug,
    }


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not _allowed(update.effective_user.id):
        if update.message:
            await update.message.reply_text("Unauthorized.")
        return
    if update.message:
        await update.message.reply_text(
            HOME_TEXT,
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not _allowed(update.effective_user.id):
        return
    if update.message:
        text, keyboard = help_screen()
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )


async def on_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route inline menu navigation without exposing tool execution as callbacks."""
    query = update.callback_query
    user = update.effective_user
    if not query:
        return
    if not user or not _allowed(user.id):
        await query.answer("Unauthorized.", show_alert=True)
        return

    await query.answer()
    destination = query.data or ""
    if destination == "menu:home":
        text, keyboard = HOME_TEXT, home_keyboard()
    elif destination == "menu:tools":
        text, keyboard = tools_screen()
    elif destination == "menu:mcp":
        text, keyboard = mcp_screen()
    elif destination == "menu:help":
        text, keyboard = help_screen()
    elif destination == "menu:chat":
        text = (
            "<b>Chat mode</b>\n\n"
            "Send your next message normally. Nally will use available tools when needed.\n"
            "Send a <b>PDF / TXT / MD</b> document to ingest it into your study library."
        )
        keyboard = home_keyboard()
    else:
        text, keyboard = HOME_TEXT, home_keyboard()

    try:
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    except Exception:
        logger.exception("Telegram inline menu update failed")
        if query.message:
            await query.message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )


async def _deliver_reply(
    *,
    status_message,
    reply: str,
    chat_id: int,
    bot_token: str,
) -> None:
    """Send agent reply: Rich Message for tables, else HTML, else plain text."""
    reply = (reply or "").strip() or "(Nally returned an empty response.)"

    if len(reply) <= _RICH_MARKDOWN_LIMIT and contains_markdown_table(reply):
        try:
            transport = TelegramRichTransport(bot_token)
            await transport.edit_markdown(
                chat_id=chat_id,
                message_id=status_message.message_id,
                markdown=reply,
            )
            return
        except TelegramRichMessageError as exc:
            logger.warning("Telegram rich message failed; falling back to HTML: %s", exc)

    rendered = render_telegram_html(reply)
    chunks = split_telegram_html(rendered, limit=3900)
    if not chunks:
        chunks = ["(Nally returned an empty response.)"]

    send_parse_mode = ParseMode.HTML
    try:
        await status_message.edit_text(chunks[0], parse_mode=send_parse_mode)
    except Exception:
        logger.exception("Telegram HTML rendering/send failed; retrying as plain text")
        send_parse_mode = None
        plain = reply
        chunks = [plain[i : i + 3900] for i in range(0, len(plain), 3900)] or [
            "(Nally returned an empty response.)"
        ]
        try:
            await status_message.edit_text(chunks[0])
        except Exception:
            await status_message.reply_text(chunks[0])

    for chunk in chunks[1:]:
        await status_message.reply_text(chunk, parse_mode=send_parse_mode)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    user = update.effective_user
    if not user or not _allowed(user.id):
        await update.message.reply_text("Unauthorized.")
        return

    text = update.message.text.strip()
    if not text:
        return

    status = await update.message.reply_text("Thinking…")
    session_id = f"tg:{user.id}"

    def _run():
        from nally.agent.graph import run_agent

        return run_agent(text, session_id=session_id)

    try:
        reply = await asyncio.to_thread(_run)
    except Exception as e:
        logger.exception("telegram agent failed")
        reply = f"Error: {e}"

    token = context.bot.token if context.bot else TELEGRAM_BOT_TOKEN
    await _deliver_reply(
        status_message=status,
        reply=str(reply),
        chat_id=status.chat_id,
        bot_token=token or "",
    )


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ingest an uploaded study document into the personal library."""
    if not update.message or not update.message.document:
        return
    user = update.effective_user
    if not user or not _allowed(user.id):
        await update.message.reply_text("Unauthorized.")
        return

    doc = update.message.document
    filename = doc.file_name or "document.txt"
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED_DOC_SUFFIXES:
        await update.message.reply_text(
            f"Unsupported file type `{suffix or 'unknown'}`. "
            "Send a PDF, TXT, or Markdown file."
        )
        return

    max_bytes = max(1, LIBRARY_MAX_UPLOAD_MB) * 1024 * 1024
    if doc.file_size and doc.file_size > max_bytes:
        await update.message.reply_text(
            f"File is too large ({doc.file_size // (1024 * 1024)} MB). "
            f"Limit is {LIBRARY_MAX_UPLOAD_MB} MB."
        )
        return

    meta = _parse_ingest_caption(update.message.caption, filename)
    status = await update.message.reply_text(
        f"Ingesting <b>{meta['title']}</b>…", parse_mode=ParseMode.HTML
    )

    def _ingest() -> dict:
        from nally.library.ingest import ingest_file

        WORKSPACE.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(WORKSPACE)) as tmp:
            dest = Path(tmp) / filename
            # Download is async on the bot; we bridge below.
            return {"_path": str(dest), "_meta": meta}

    # Download on the event loop, ingest in a worker thread.
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(WORKSPACE)) as tmp:
            dest = Path(tmp) / re.sub(r"[^a-zA-Z0-9._-]+", "_", filename)
            await tg_file.download_to_drive(custom_path=str(dest))

            def _run_ingest() -> dict:
                from nally.library.ingest import ingest_file

                return ingest_file(
                    dest,
                    title=meta["title"],
                    doc_type=meta["doc_type"],
                    jurisdiction=meta["jurisdiction"],
                    slug=meta["slug"] or None,
                    embed=True,
                )

            result = await asyncio.to_thread(_run_ingest)
    except Exception as e:
        logger.exception("telegram document ingest failed")
        await status.edit_text(f"Ingest failed: {e}")
        return

    await status.edit_text(
        (
            f"Library updated.\n"
            f"• <b>{result['title']}</b>\n"
            f"• slug: <code>{result['slug']}</code>\n"
            f"• chunks: {result['chunks']}\n"
            f"• embedded: {result['embedded']}\n\n"
            f"Ask me about it anytime."
        ),
        parse_mode=ParseMode.HTML,
    )


def build_application() -> Optional[Application]:
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set — Telegram disabled")
        return None

    builder = Application.builder().token(TELEGRAM_BOT_TOKEN)
    if TELEGRAM_MODE == "webhook":
        builder = builder.updater(None)
    app = builder.build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(on_menu_callback, pattern=r"^menu:"))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app


async def setup_telegram(application: Application, webhook_url: str | None) -> None:
    await application.initialize()
    await application.start()
    if webhook_url:
        url = webhook_url.rstrip("/")
        if not url.endswith("/telegram/webhook"):
            url = f"{url}/telegram/webhook"
        kwargs = {"url": url, "drop_pending_updates": False}
        if TELEGRAM_WEBHOOK_SECRET:
            kwargs["secret_token"] = TELEGRAM_WEBHOOK_SECRET
        await application.bot.set_webhook(**kwargs)
        logger.info("Telegram webhook set: %s", url)
    else:
        logger.info("Telegram app started (mode=%s)", TELEGRAM_MODE)


async def shutdown_telegram(application: Application) -> None:
    # NEVER deleteWebhook on shutdown — Render old instance would wipe new webhook.
    await application.stop()
    await application.shutdown()
