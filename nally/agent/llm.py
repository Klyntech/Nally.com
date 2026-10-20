"""LLM client with classified provider failures and fast healthy fallbacks."""
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
    NVIDIA_NIM_API_KEY,
    NVIDIA_NIM_BASE_URL,
    NVIDIA_NIM_MODEL,
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


def _failure_scope(exc: BaseException) -> str:
    """Return 'provider' for failures unlikely to improve by changing models."""
    status = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    detail = str(exc).lower()

    # These indicate account/provider-wide constraints, not a bad model choice.
    if status in (401, 402, 429) or any(
        marker in detail
        for marker in (
            "free-models-per-day",
            "insufficient credits",
            "insufficient account funds",
            "billing hard limit",
            "quota exceeded",
            "daily quota",
            "rate limit exceeded",
        )
    ):
        return "provider"
    # A 403 can be model-specific (e.g. model access disabled), so let the
    # next model on that same provider have a chance.
    return "model"


def _ses_id() -> str:
    """OpenCode-shaped session id: ses_ + 12 hex + 14 base62."""
    counter = secrets.randbelow(64)
    n = (~(int(time.time() * 1000) * 0x1000 + counter)) & ((1 << 48) - 1)
    hex12 = f"{n:012x}"
    tail = "".join(secrets.choice(_B62) for _ in range(14))
    return f"ses_{hex12}{tail}"


def _msg_id() -> str:
    return "msg_" + secrets.token_hex(12)


def _openrouter_client(timeout: float = 60.0) -> OpenAI | None:
    if not OPENROUTER_API_KEY:
        return None
    # Bound client timeout; caller may pass a tighter remaining-budget value.
    return OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
        timeout=max(1.0, min(float(timeout), 60.0)),
    )


def _call_openrouter(
    client: OpenAI,
    model: str,
    messages: list,
    tools: list | None,
    timeout: float | None = None,
):
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
    if timeout is not None:
        # openai client also accepts per-request timeout
        kwargs["timeout"] = max(1.0, float(timeout))
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


def _call_opencode_zen(
    model: str,
    messages: list,
    tools: list | None,
    timeout: float | None = None,
):
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
    # Cap at 90s historical default; caller may tighten to remaining wall budget.
    request_timeout = max(1.0, min(float(timeout) if timeout is not None else 90.0, 90.0))

    with httpx.Client(timeout=request_timeout) as client:
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


def _call_nvidia_nim(
    messages: list,
    tools: list | None,
    model: str | None = None,
    timeout: float | None = None,
):
    """Call NVIDIA NIM through its OpenAI-compatible hosted endpoint."""
    if not NVIDIA_NIM_API_KEY:
        raise RuntimeError("NVIDIA_NIM_API_KEY not set")

    request_timeout = max(1.0, min(float(timeout) if timeout is not None else 60.0, 60.0))
    client = OpenAI(
        base_url=NVIDIA_NIM_BASE_URL,
        api_key=NVIDIA_NIM_API_KEY,
        timeout=request_timeout,
    )
    kwargs: dict = {
        "model": model or NVIDIA_NIM_MODEL,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 4096,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    return client.chat.completions.create(**kwargs)


def chat_completion(
    messages: list,
    tools: list | None = None,
    model: str | None = None,
    timeout: float | None = None,
):
    """Try OpenRouter, then the known-good NVIDIA NIM fallback, then OpenCode Zen.

    ``timeout`` is an optional *shared* remaining-budget bound (seconds) for the
    entire fallback chain. Each attempt uses only the time still left after prior
    attempts; later providers cannot re-spend the full original budget.
    Per-operation duration and outcome are logged without secrets or prompts.
    """
    primary_model = model or MODEL
    last_err: BaseException | None = None
    # Shared end-to-end deadline for this chat_completion call (all providers).
    deadline: float | None = None
    if timeout is not None:
        if float(timeout) <= 0:
            raise TimeoutError(f"chat_completion budget already exhausted ({timeout}s)")
        deadline = time.monotonic() + float(timeout)

    def _remaining() -> float | None:
        if deadline is None:
            return None
        return deadline - time.monotonic()

    def _slice(cap: float) -> float:
        """Timeout for the next attempt: min(provider cap, remaining budget)."""
        rem = _remaining()
        if rem is None:
            return cap
        if rem <= 0:
            raise TimeoutError("chat_completion shared deadline exhausted")
        # Never start an attempt with less than 0.25s; caller should have stopped.
        return max(0.25, min(cap, rem))

    def _log_attempt(provider: str, selected_model: str, started: float, ok: bool, err: str = ""):
        elapsed = time.monotonic() - started
        if ok:
            logger.info(
                "llm_request provider=%s model=%s duration_s=%.2f status=ok",
                provider,
                selected_model,
                elapsed,
            )
        else:
            logger.warning(
                "llm_request provider=%s model=%s duration_s=%.2f status=error error=%s",
                provider,
                selected_model,
                elapsed,
                (err or "unknown")[:200],
            )

    # 1) OpenRouter. Skip the rest of this provider on account-wide failures.
    try:
        or_timeout = _slice(60.0)
    except TimeoutError as te:
        raise te
    or_client = _openrouter_client(timeout=or_timeout)
    if or_client is not None:
        tried: set[str] = set()
        candidates = [primary_model] + [m for m in FALLBACK_MODELS if m != primary_model]
        for candidate in candidates:
            if candidate in tried:
                continue
            tried.add(candidate)
            try:
                attempt_timeout = _slice(60.0)
            except TimeoutError:
                logger.warning("OpenRouter skipped: shared deadline exhausted before model %s", candidate)
                break
            started = time.monotonic()
            try:
                resp = _call_openrouter(
                    or_client, candidate, messages, tools, timeout=attempt_timeout
                )
                _log_attempt("openrouter", candidate, started, ok=True)
                if candidate != primary_model:
                    logger.info("OpenRouter fallback model ok: %s", candidate)
                return resp
            except Exception as exc:
                last_err = exc
                _log_attempt("openrouter", candidate, started, ok=False, err=str(exc))
                scope = _failure_scope(exc)
                logger.warning(
                    "OpenRouter model %s failed (scope=%s): %s",
                    candidate,
                    scope,
                    exc,
                )
                if scope == "provider":
                    break
    else:
        logger.warning("OPENROUTER_API_KEY not set; skipping OpenRouter")

    # 2) NVIDIA NIM has been observed healthy in production logs. Try it before
    # spending time cycling through Zen models that may be disabled or unfunded.
    if NVIDIA_NIM_API_KEY:
        try:
            attempt_timeout = _slice(60.0)
        except TimeoutError:
            logger.warning("NVIDIA NIM skipped: shared deadline exhausted")
            attempt_timeout = None
        if attempt_timeout is not None:
            started = time.monotonic()
            try:
                logger.info("Falling back to NVIDIA NIM model: %s", NVIDIA_NIM_MODEL)
                resp = _call_nvidia_nim(messages, tools, timeout=attempt_timeout)
                _log_attempt("nvidia_nim", NVIDIA_NIM_MODEL, started, ok=True)
                return resp
            except Exception as exc:
                last_err = exc
                _log_attempt("nvidia_nim", NVIDIA_NIM_MODEL, started, ok=False, err=str(exc))
                logger.warning("NVIDIA NIM failed: %s", exc)
    else:
        logger.warning("NVIDIA_NIM_API_KEY not set; skipping NVIDIA NIM")

    # 3) OpenCode Zen. Stop trying models on provider-wide billing/quota failures.
    if OPENCODE_API_KEY:
        zen_models = [OPENCODE_MODEL] + [
            m for m in OPENCODE_FALLBACK_MODELS if m != OPENCODE_MODEL
        ]
        free_defaults = [
            "big-pickle",
            "nemotron-3.5-lightning-free",
            "mimo-v2.6-flash-free",
            "glm-5.3-flash-free",
            "deepseek-v4.1-flash-free",
        ]
        ordered: list[str] = []
        for candidate in zen_models + free_defaults:
            if candidate not in ordered:
                ordered.append(candidate)

        for candidate in ordered:
            try:
                attempt_timeout = _slice(90.0)
            except TimeoutError:
                logger.warning("OpenCode Zen skipped: shared deadline exhausted before model %s", candidate)
                break
            started = time.monotonic()
            try:
                logger.info("Falling back to OpenCode Zen model: %s", candidate)
                resp = _call_opencode_zen(candidate, messages, tools, timeout=attempt_timeout)
                _log_attempt("opencode_zen", candidate, started, ok=True)
                return resp
            except Exception as exc:
                last_err = exc
                _log_attempt("opencode_zen", candidate, started, ok=False, err=str(exc))
                scope = _failure_scope(exc)
                logger.warning(
                    "OpenCode Zen model %s failed (scope=%s): %s",
                    candidate,
                    scope,
                    exc,
                )
                if scope == "provider":
                    break
    else:
        logger.warning("OPENCODE_API_KEY not set; skipping OpenCode Zen")

    if isinstance(last_err, TimeoutError) or (
        last_err is None and deadline is not None and time.monotonic() >= deadline
    ):
        raise TimeoutError("chat_completion shared deadline exhausted")
    raise last_err or RuntimeError(
        "All configured LLM providers failed (OpenRouter, NVIDIA NIM, OpenCode Zen)"
    )
