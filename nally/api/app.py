"""FastAPI app — health, chat, Telegram webhook."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from telegram import Update
from telegram.ext import Application

from nally import __version__
from nally.config import (
    ACCESS_TOKEN,
    MODEL,
    NALLY_BASE_URL,
    PROVIDER,
    TELEGRAM_MODE,
    TELEGRAM_WEBHOOK_SECRET,
)
from nally.core.logging import logger

_tg_app: Optional[Application] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _tg_app
    if TELEGRAM_MODE != "off":
        from nally.telegram.bot import build_application, setup_telegram, shutdown_telegram

        _tg_app = build_application()
        if _tg_app is not None:
            webhook_url = NALLY_BASE_URL if TELEGRAM_MODE == "webhook" and NALLY_BASE_URL else None
            await setup_telegram(_tg_app, webhook_url)
            if TELEGRAM_MODE == "polling" and _tg_app.updater is not None:
                await _tg_app.updater.start_polling(drop_pending_updates=True)
                logger.info("Telegram polling started")
            elif TELEGRAM_MODE == "webhook" and not NALLY_BASE_URL:
                logger.warning("TELEGRAM_MODE=webhook but NALLY_BASE_URL is empty — set public URL")
    yield
    if _tg_app is not None:
        from nally.telegram.bot import shutdown_telegram

        if TELEGRAM_MODE == "polling" and _tg_app.updater is not None:
            await _tg_app.updater.stop()
        await shutdown_telegram(_tg_app)
        _tg_app = None


app = FastAPI(title="Nally.com", version=__version__, lifespan=lifespan)


def require_auth(authorization: str | None = Header(default=None)):
    if not ACCESS_TOKEN:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Bearer token")
    if authorization.removeprefix("Bearer ").strip() != ACCESS_TOKEN:
        raise HTTPException(403, "Invalid token")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=20000)
    session_id: str = "default"


class ChatResponse(BaseModel):
    reply: str
    model: str
    provider: str


@app.get("/")
def root():
    return {"ok": True, "service": "nally.com", "health": "/health"}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": __version__,
        "provider": PROVIDER,
        "model": MODEL,
        "telegram": TELEGRAM_MODE if _tg_app else "off",
    }


@app.post("/v1/chat", response_model=ChatResponse)
def chat(body: ChatRequest, _auth=Depends(require_auth)):
    from nally.agent.graph import run_agent

    logger.info("chat session=%s len=%d", body.session_id, len(body.message))
    try:
        reply = run_agent(body.message, session_id=body.session_id)
    except Exception as e:
        logger.exception("agent failed")
        raise HTTPException(500, str(e)) from e
    return ChatResponse(reply=reply, model=MODEL, provider=PROVIDER)


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    if _tg_app is None:
        raise HTTPException(503, "Telegram not configured")

    # Only enforce secret when Telegram actually sends the header.
    # If TELEGRAM_WEBHOOK_SECRET is set in env but setWebhook was called without
    # secret_token, Telegram won't send the header — rejecting would 403 forever.
    if TELEGRAM_WEBHOOK_SECRET:
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if secret and secret != TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(403, "Bad webhook secret")

    data = await request.json()
    update = Update.de_json(data, _tg_app.bot)

    # ACK immediately; process in background so Telegram doesn't time out / retry.
    async def _process():
        try:
            await _tg_app.process_update(update)
        except Exception:
            logger.exception("telegram process_update failed")

    asyncio.create_task(_process())
    return {"ok": True}
