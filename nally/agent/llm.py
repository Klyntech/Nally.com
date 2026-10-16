"""OpenRouter OpenAI-compatible client."""
from __future__ import annotations

from openai import OpenAI

from nally.config import (
    FALLBACK_MODELS,
    MODEL,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_REASONING,
)
from nally.core.logging import logger


def get_client() -> OpenAI:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    return OpenAI(base_url=OPENROUTER_BASE_URL, api_key=OPENROUTER_API_KEY, timeout=60.0)


def chat_completion(messages: list, tools: list | None = None, model: str | None = None):
    client = get_client()
    model = model or MODEL
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 4096,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    # Explicitly enable/disable reasoning for models that support it
    m = model.lower()
    if any(x in m for x in ("lightning", "reasoning", "nemotron-3.5")):
        kwargs["extra_body"] = {"reasoning": {"enabled": bool(OPENROUTER_REASONING)}}

    last_err = None
    tried = []
    for candidate in [model] + [m for m in FALLBACK_MODELS if m != model]:
        if candidate in tried:
            continue
        tried.append(candidate)
        kwargs["model"] = candidate
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as e:
            last_err = e
            logger.warning("Model %s failed: %s", candidate, e)
            continue
    raise last_err or RuntimeError("All models failed")
