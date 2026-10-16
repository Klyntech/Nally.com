"""FastAPI app — health + chat."""
from __future__ import annotations

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from nally import __version__
from nally.config import ACCESS_TOKEN, MODEL, PROVIDER
from nally.core.logging import logger

app = FastAPI(title="Nally.com", version=__version__)


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


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__, "provider": PROVIDER, "model": MODEL}


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
