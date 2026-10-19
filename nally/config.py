"""Nally.com configuration — env only."""
from __future__ import annotations

import json
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

# NVIDIA NIM (second-provider fallback before OpenCode Zen)
NVIDIA_NIM_API_KEY = os.getenv("NVIDIA_NIM_API_KEY", "")
NVIDIA_NIM_BASE_URL = os.getenv("NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_NIM_MODEL = os.getenv("NVIDIA_NIM_MODEL", "nvidia/nemotron-3.5-super-vl-120b-a12b")

# NVIDIA embeddings (document library / RAG)
NVIDIA_EMBED_API_KEY = (
    os.getenv("NVIDIA_EMBED_API_KEY", "").strip()
    or os.getenv("NVIDIA_API_KEY", "").strip()
    or NVIDIA_NIM_API_KEY.strip()
)
NVIDIA_EMBED_BASE_URL = os.getenv(
    "NVIDIA_EMBED_BASE_URL",
    os.getenv("NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1"),
).rstrip("/")
NVIDIA_EMBED_MODEL = os.getenv(
    "NVIDIA_EMBED_MODEL", "nvidia/llama-nemotron-embed-vl-1b-v2"
)
NVIDIA_EMBED_DIM = int(os.getenv("NVIDIA_EMBED_DIM", "2048"))

# Study library defaults
LIBRARY_DEFAULT_JURISDICTION = os.getenv("LIBRARY_DEFAULT_JURISDICTION", "").strip()
LIBRARY_MAX_UPLOAD_MB = int(os.getenv("LIBRARY_MAX_UPLOAD_MB", "20"))

# Auth. NALLY_ACCESS_TOKENS is a JSON object mapping principal names to bearer tokens.
# The legacy single token remains supported as one shared principal.
ACCESS_TOKEN = os.getenv("NALLY_ACCESS_TOKEN", "").strip()
_raw_access_tokens = os.getenv("NALLY_ACCESS_TOKENS", "").strip()
if _raw_access_tokens:
    try:
        _parsed_access_tokens = json.loads(_raw_access_tokens)
    except json.JSONDecodeError as exc:
        raise RuntimeError("NALLY_ACCESS_TOKENS must be a JSON object") from exc
    if not isinstance(_parsed_access_tokens, dict) or not _parsed_access_tokens:
        raise RuntimeError("NALLY_ACCESS_TOKENS must be a non-empty JSON object")
    if any(
        not isinstance(principal, str)
        or not principal.strip()
        or not isinstance(token, str)
        or not token.strip()
        for principal, token in _parsed_access_tokens.items()
    ):
        raise RuntimeError("NALLY_ACCESS_TOKENS keys and values must be non-empty strings")
    ACCESS_TOKENS = {
        principal.strip(): token.strip()
        for principal, token in _parsed_access_tokens.items()
    }
    if len(set(ACCESS_TOKENS.values())) != len(ACCESS_TOKENS):
        raise RuntimeError("NALLY_ACCESS_TOKENS must not reuse a token for multiple principals")
else:
    ACCESS_TOKENS: dict[str, str] = {}

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Limits
MAX_ITERATIONS = int(os.getenv("NALLY_MAX_ITERATIONS", "12"))
MAX_TOOL_CALLS = int(os.getenv("NALLY_MAX_TOOL_CALLS", "20"))
MAX_WALL_TIME = int(os.getenv("NALLY_MAX_WALL_TIME", "90"))
CMD_TIMEOUT = int(os.getenv("NALLY_CMD_TIMEOUT", "30"))
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

FALLBACK_MODELS = [
    MODEL,
    "liquid/lfm-2.5-2.6b:free",
    "nvidia/nemotron-3.5-lightning:free",
    "google/gemini-2.5-flash",
    "openai/gpt-4o-mini",
]
