"""Nally.com configuration — env only."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists():
    load_dotenv(_env, override=True)

# Provider
PROVIDER = os.getenv("NALLY_PROVIDER", "openrouter").lower()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
MODEL = os.getenv("NALLY_MODEL", "nvidia/nemotron-3.5-lightning:free")
OPENROUTER_REASONING = os.getenv("NALLY_OPENROUTER_REASONING", "true").lower() in ("1", "true", "yes")

# Auth
ACCESS_TOKEN = os.getenv("NALLY_ACCESS_TOKEN", "")

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Limits
MAX_ITERATIONS = int(os.getenv("NALLY_MAX_ITERATIONS", "12"))
MAX_TOOL_CALLS = int(os.getenv("NALLY_MAX_TOOL_CALLS", "20"))
MAX_WALL_TIME = int(os.getenv("NALLY_MAX_WALL_TIME", "90"))
CMD_TIMEOUT = int(os.getenv("NALLY_CMD_TIMEOUT", "30"))
MAX_TOOL_OUTPUT = int(os.getenv("NALLY_MAX_TOOL_OUTPUT", "20000"))

# Workspace sandbox
WORKSPACE = Path(os.getenv("NALLY_WORKSPACE", "/tmp/nally-workspace")).resolve()

# Server
PORT = int(os.getenv("PORT", os.getenv("NALLY_PORT", "10000")))
NALLY_BASE_URL = os.getenv("NALLY_BASE_URL", "").rstrip("/")

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_USER_ID = int(os.getenv("TELEGRAM_USER_ID", "0") or "0")
TELEGRAM_MODE = os.getenv("TELEGRAM_MODE", "webhook").lower()  # webhook | polling | off
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")

# Fallback models (OpenRouter)
FALLBACK_MODELS = [
    MODEL,
    "google/gemini-2.5-flash",
    "openai/gpt-4o-mini",
]
