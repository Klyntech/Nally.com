"""FastAPI app: health, authenticated chat, and Telegram webhook."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from telegram import Update
from telegram.ext import Application

from nally import __version__
from nally.config import (
    ACCESS_TOKEN,
    ACCESS_TOKENS,
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


def _token_identity(principal: str) -> str:
    """Return a stable, non-secret namespace for one authenticated principal."""
    return hashlib.sha256(principal.encode("utf-8")).hexdigest()[:16]


def require_auth(authorization: str | None = Header(default=None)) -> str:
    """Fail closed unless a configured principal's bearer token matches."""
    legacy_token = (ACCESS_TOKEN or "").strip()
    if not legacy_token and not ACCESS_TOKENS:
        raise HTTPException(503, "API authentication is not configured")

    scheme, _, supplied = (authorization or "").partition(" ")
    supplied = supplied.strip()
    if scheme.lower() != "bearer" or not supplied:
        raise HTTPException(401, "Invalid or missing bearer token")

    matched_principal = None
    for principal, candidate in ACCESS_TOKENS.items():
        if hmac.compare_digest(supplied, candidate):
            matched_principal = principal
    if matched_principal is not None:
        return _token_identity(f"named:{matched_principal}")

    if legacy_token and hmac.compare_digest(supplied, legacy_token):
        return _token_identity(f"legacy:{legacy_token}")
    raise HTTPException(401, "Invalid or missing bearer token")


def _verify_telegram_webhook_secret(secret: str | None) -> None:
    """Require Telegram's configured secret header; missing configuration fails closed."""
    expected = (TELEGRAM_WEBHOOK_SECRET or "").strip()
    if not expected:
        raise HTTPException(503, "Telegram webhook secret is not configured")
    supplied = (secret or "").strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(403, "Invalid Telegram webhook secret")


def _api_session_id(identity: str, requested_session_id: str) -> str:
    """Namespace API sessions so callers cannot address Telegram/internal sessions."""
    return f"api:{identity}:{requested_session_id}"


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=20000)
    session_id: str = Field(default="default", min_length=1, max_length=128)


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
def chat(body: ChatRequest, identity: str = Depends(require_auth)):
    from nally.agent.graph import run_agent

    session_id = _api_session_id(identity, body.session_id)
    logger.info("chat session=%s len=%d", session_id, len(body.message))
    try:
        reply = run_agent(body.message, session_id=session_id)
    except Exception as e:
        logger.exception("agent failed")
        raise HTTPException(500, "Agent request failed") from e
    return ChatResponse(reply=reply, model=MODEL, provider=PROVIDER)


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    if _tg_app is None:
        raise HTTPException(503, "Telegram not configured")

    _verify_telegram_webhook_secret(
        request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    )

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
