"""LLM client: OpenRouter primary, OpenCode Zen fallback on rate-limit/unavailable."""
from __future__ import annotations

from openai import OpenAI

from nally.config import (
    FALLBACK_MODELS,
    MODEL,
    OPENCODE_API_KEY,
    OPENCODE_BASE_URL,
    OPENCODE_FALLBACK_MODELS,
    OPENCODE_MODEL,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_REASONING,
)
from nally.core.logging import logger


def _is_rate_or_unavailable(exc: BaseException) -> bool:
    t = (str(exc) + str(getattr(exc, "__cause__", "") or "")).lower()
    markers = (
        "429",
        "rate limit",
        "rate_limit",
        "too many requests",
        "freeusagelimit",
        "quota",
        "503",
        "502",
        "504",
        "unavailable",
        "overloaded",
        "capacity",
        "timeout",
        "connection",
    )
    return any(m in t for m in markers)


def _openrouter_client() -> OpenAI | None:
    if not OPENROUTER_API_KEY:
        return None
    return OpenAI(base_url=OPENROUTER_BASE_URL, api_key=OPENROUTER_API_KEY, timeout=60.0)


def _opencode_client() -> OpenAI | None:
    if not OPENCODE_API_KEY:
        return None
    return OpenAI(base_url=OPENCODE_BASE_URL, api_key=OPENCODE_API_KEY, timeout=60.0)


def _call(client: OpenAI, model: str, messages: list, tools: list | None, use_reasoning_flag: bool):
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 4096,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    if use_reasoning_flag:
        m = model.lower()
        if any(x in m for x in ("lightning", "reasoning", "nemotron-3.5")):
            kwargs["extra_body"] = {"reasoning": {"enabled": bool(OPENROUTER_REASONING)}}

    return client.chat.completions.create(**kwargs)


def chat_completion(messages: list, tools: list | None = None, model: str | None = None):
    """Try OpenRouter models, then OpenCode Zen free models."""
    primary_model = model or MODEL
    last_err: BaseException | None = None

    # ── 1) OpenRouter ──────────────────────────────────────────
    or_client = _openrouter_client()
    if or_client is not None:
        tried: list[str] = []
        for candidate in [primary_model] + [m for m in FALLBACK_MODELS if m != primary_model]:
            if candidate in tried:
                continue
            tried.append(candidate)
            try:
                resp = _call(or_client, candidate, messages, tools, use_reasoning_flag=True)
                if candidate != primary_model:
                    logger.info("OpenRouter fallback model ok: %s", candidate)
                return resp
            except Exception as e:
                last_err = e
                logger.warning("OpenRouter model %s failed: %s", candidate, e)
                if not _is_rate_or_unavailable(e):
                    # non-transient: still try next model, then Zen
                    continue
    else:
        logger.warning("OPENROUTER_API_KEY not set — skipping OpenRouter")

    # ── 2) OpenCode Zen ────────────────────────────────────────
    zen = _opencode_client()
    if zen is None:
        raise last_err or RuntimeError(
            "All LLM providers failed. Set OPENROUTER_API_KEY and/or OPENCODE_API_KEY."
        )

    zen_models = [OPENCODE_MODEL] + [m for m in OPENCODE_FALLBACK_MODELS if m != OPENCODE_MODEL]
    tried_zen: list[str] = []
    for candidate in zen_models:
        if candidate in tried_zen:
            continue
        tried_zen.append(candidate)
        try:
            logger.info("Falling back to OpenCode Zen model: %s", candidate)
            return _call(zen, candidate, messages, tools, use_reasoning_flag=False)
        except Exception as e:
            last_err = e
            logger.warning("OpenCode Zen model %s failed: %s", candidate, e)
            continue

    raise last_err or RuntimeError("OpenRouter and OpenCode Zen both failed")
