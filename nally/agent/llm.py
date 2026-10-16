"""LLM client: OpenRouter primary, OpenCode Zen fallback (with free-tier fingerprint)."""
from __future__ import annotations

import json
import secrets
import string
import time
from types import SimpleNamespace

import httpx
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

_B62 = string.ascii_letters + string.digits
_OPENCODE_UA = "opencode/1.18.34 ai-sdk/provider-utils/4.0.23 runtime/python"

# Zen free-tier gate requires these tool names present in the request body.
_ZEN_REQUIRED_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Execute a shell command",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob",
            "description": "Find files by pattern",
            "parameters": {
                "type": "object",
                "properties": {"pattern": {"type": "string"}},
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Search file contents",
            "parameters": {
                "type": "object",
                "properties": {"pattern": {"type": "string"}},
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Read a file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
]


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


def _ses_id() -> str:
    """OpenCode-shaped session id: ses_ + 12 hex + 14 base62."""
    counter = secrets.randbelow(64)
    n = (~(int(time.time() * 1000) * 0x1000 + counter)) & ((1 << 48) - 1)
    hex12 = f"{n:012x}"
    tail = "".join(secrets.choice(_B62) for _ in range(14))
    return f"ses_{hex12}{tail}"


def _msg_id() -> str:
    return "msg_" + secrets.token_hex(12)


def _openrouter_client() -> OpenAI | None:
    if not OPENROUTER_API_KEY:
        return None
    return OpenAI(base_url=OPENROUTER_BASE_URL, api_key=OPENROUTER_API_KEY, timeout=60.0)


def _call_openrouter(client: OpenAI, model: str, messages: list, tools: list | None):
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 4096,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    m = model.lower()
    if any(x in m for x in ("lightning", "reasoning", "nemotron-3.5")):
        kwargs["extra_body"] = {"reasoning": {"enabled": bool(OPENROUTER_REASONING)}}
    return client.chat.completions.create(**kwargs)


def _merge_zen_tools(tools: list | None) -> list:
    """Ensure bash/glob/grep/read exist (Zen free-tier gate)."""
    existing = {t.get("function", {}).get("name") for t in (tools or []) if isinstance(t, dict)}
    out = list(tools or [])
    for req in _ZEN_REQUIRED_TOOLS:
        name = req["function"]["name"]
        if name not in existing:
            out.append(req)
    return out


def _call_opencode_zen(model: str, messages: list, tools: list | None):
    """Zen free tier: stream=true + opencode headers + required tools; aggregate SSE."""
    if not OPENCODE_API_KEY:
        raise RuntimeError("OPENCODE_API_KEY not set")

    sid = _ses_id()
    headers = {
        "Authorization": f"Bearer {OPENCODE_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": _OPENCODE_UA,
        "x-opencode-client": "cli",
        "x-opencode-project": "global",
        "x-opencode-session": sid,
        "x-opencode-session-id": sid,
        "x-opencode-request": _msg_id(),
    }
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 4096,
        "stream": True,
        "tools": _merge_zen_tools(tools),
        "tool_choice": "auto",
    }
    url = OPENCODE_BASE_URL.rstrip("/") + "/chat/completions"

    content_parts: list[str] = []
    tool_acc: dict[int, dict] = {}

    with httpx.Client(timeout=90.0) as client:
        with client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code >= 400:
                text = resp.read().decode(errors="replace")
                raise RuntimeError(f"OpenCode Zen HTTP {resp.status_code}: {text[:300]}")
            for line in resp.iter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    payload = line[6:].strip()
                elif line.startswith("data:"):
                    payload = line[5:].strip()
                else:
                    continue
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                if delta.get("content"):
                    content_parts.append(delta["content"])
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    slot = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["arguments"] += fn["arguments"]

    tool_calls = []
    for idx in sorted(tool_acc):
        slot = tool_acc[idx]
        if not slot["name"]:
            continue
        tool_calls.append(
            SimpleNamespace(
                id=slot["id"] or f"call_{idx}",
                type="function",
                function=SimpleNamespace(name=slot["name"], arguments=slot["arguments"] or "{}"),
            )
        )

    message = SimpleNamespace(
        content="".join(content_parts) or None,
        tool_calls=tool_calls or None,
        role="assistant",
    )
    choice = SimpleNamespace(message=message, finish_reason="stop", index=0)
    return SimpleNamespace(choices=[choice], model=model)


def chat_completion(messages: list, tools: list | None = None, model: str | None = None):
    """Try OpenRouter models, then OpenCode Zen."""
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
                resp = _call_openrouter(or_client, candidate, messages, tools)
                if candidate != primary_model:
                    logger.info("OpenRouter fallback model ok: %s", candidate)
                return resp
            except Exception as e:
                last_err = e
                logger.warning("OpenRouter model %s failed: %s", candidate, e)
                continue
    else:
        logger.warning("OPENROUTER_API_KEY not set — skipping OpenRouter")

    # ── 2) OpenCode Zen (headers + stream + required tools) ────
    if not OPENCODE_API_KEY:
        raise last_err or RuntimeError(
            "All LLM providers failed. Set OPENROUTER_API_KEY and/or OPENCODE_API_KEY."
        )

    zen_models = [OPENCODE_MODEL] + [m for m in OPENCODE_FALLBACK_MODELS if m != OPENCODE_MODEL]
    free_defaults = [
        "big-pickle",
        "nemotron-3.5-lightning-free",
        "mimo-v2.6-flash-free",
        "glm-5.3-flash-free",
        "deepseek-v4.1-flash-free",
    ]
    ordered = []
    for m in zen_models + free_defaults:
        if m not in ordered:
            ordered.append(m)

    for candidate in ordered:
        try:
            logger.info("Falling back to OpenCode Zen model: %s", candidate)
            return _call_opencode_zen(candidate, messages, tools)
        except Exception as e:
            last_err = e
            logger.warning("OpenCode Zen model %s failed: %s", candidate, e)
            continue

    raise last_err or RuntimeError("OpenRouter and OpenCode Zen both failed")
