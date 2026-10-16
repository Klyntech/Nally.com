"""Telegram bot — webhook (Render) or polling (local)."""
from __future__ import annotations

import asyncio
from typing import Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from nally.config import TELEGRAM_BOT_TOKEN, TELEGRAM_MODE, TELEGRAM_USER_ID, TELEGRAM_WEBHOOK_SECRET
from nally.core.logging import logger


def _allowed(user_id: int | None) -> bool:
    if not TELEGRAM_USER_ID:
        return True  # open if unset (dev)
    return user_id is not None and int(user_id) == int(TELEGRAM_USER_ID)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not _allowed(update.effective_user.id):
        if update.message:
            await update.message.reply_text("Unauthorized.")
        return
    await update.message.reply_text("Nally online. Send a message.")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not _allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        "Tools: memory, files, shell (workspace).\n"
        "Just chat — I'll use tools when needed."
    )


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

    if len(reply) > 4000:
        reply = reply[:4000] + "\n…[truncated]"

    try:
        await status.edit_text(reply)
    except Exception:
        await update.message.reply_text(reply)


def build_application() -> Optional[Application]:
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set — Telegram disabled")
        return None

    builder = Application.builder().token(TELEGRAM_BOT_TOKEN)
    # Webhook: no internal updater. Polling: keep default updater.
    if TELEGRAM_MODE == "webhook":
        builder = builder.updater(None)
    app = builder.build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app


async def setup_telegram(application: Application, webhook_url: str | None) -> None:
    """Initialize PTB application; set webhook if URL given."""
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
    # NEVER deleteWebhook on shutdown — on Render the old instance exits after
    # the new one starts and would wipe the webhook the new process just set.
    await application.stop()
    await application.shutdown()
