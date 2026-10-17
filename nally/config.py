"""Nally.com configuration — env only."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists():
    load_dotenv(_env, override=True)

# Provider (primary)
PROVIDER = os.getenv("NALLY_PROVIDER", "openrouter").lower()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
MODEL = os.getenv("NALLY_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
OPENROUTER_REASONING = os.getenv("NALLY_OPENROUTER_REASONING", "false").lower() in ("1", "true", "yes")

# OpenCode Zen (fallback after OpenRouter fails)
# NOTE: Zen *free* models return FreeTierError outside the OpenCode app.
# External API needs a funded Zen account + paid model ids (e.g. glm-5.3-flash).
OPENCODE_API_KEY = os.getenv("OPENCODE_API_KEY", "")
OPENCODE_BASE_URL = os.getenv("OPENCODE_BASE_URL", "https://opencode.ai/zen/v1")
OPENCODE_MODEL = os.getenv("OPENCODE_MODEL", "glm-5.3-flash")
OPENCODE_FALLBACK_MODELS = [
    m.strip()
    for m in os.getenv(
        "OPENCODE_FALLBACK_MODELS",
        "glm-5.3-flash,deepseek-v4-flash,minimax-m2.5,glm-5.1",
    ).split(",")
    if m.strip()
]

# NVIDIA NIM (last-resort fallback after OpenRouter and OpenCode Zen)
NVIDIA_NIM_API_KEY = os.getenv("NVIDIA_NIM_API_KEY", "")
NVIDIA_NIM_BASE_URL = os.getenv("NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_NIM_MODEL = os.getenv("NVIDIA_NIM_MODEL", "deepseek-ai/deepseek-v4-flash")

# Auth
ACCESS_TOKEN = os.getenv("NALLY_ACCESS_TOKEN", "")

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Limits
MAX_ITERATIONS = int(os.getenv("NALLY_MAX_ITERATIONS", "12"))
MAX_TOOL_CALLS = int(os.getenv("NALLY_MAX_TOOL_CALLS", "20"))
MAX_WALL_TIME = int(os.getenv("NALLY_MAX_WALL_TIME", "90"))
CMD_TIMEOUT = int(os.getenv("NALLY_CMD_TIMEOUT", "30"))
# Web search providers: Tavily primary, Brave fallback, DuckDuckGo last resort.
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()
BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY", os.getenv("BRAVE_API_KEY", "")).strip()

MAX_TOOL_OUTPUT = int(os.getenv("NALLY_MAX_TOOL_OUTPUT", "20000"))

# Workspace sandbox
WORKSPACE = Path(os.getenv("NALLY_WORKSPACE", "/tmp/nally-workspace")).resolve()

# Server
PORT = int(os.getenv("PORT", os.getenv("NALLY_PORT", "10000")))
NALLY_BASE_URL = os.getenv("NALLY_BASE_URL", "").rstrip("/")

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_USER_ID = int(os.getenv("TELEGRAM_USER_ID", "0") or "0")
TELEGRAM_MODE = os.getenv("TELEGRAM_MODE", "webhook").lower()
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")

# OpenRouter model fallbacks (same provider)
FALLBACK_MODELS = [
    MODEL,
    "liquid/lfm-2.5-2.6b:free",
    "nvidia/nemotron-3.5-lightning:free",
    "google/gemini-2.5-flash",
    "openai/gpt-4o-mini",
]
