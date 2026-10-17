from unittest.mock import MagicMock, patch

from nally.agent import llm


def test_nvidia_nim_is_tried_before_opencode_models():
    events = []
    response = object()

    def fail_openrouter(*args):
        raise RuntimeError("OpenRouter down")

    def fallback_nim(*args):
        events.append("nim")
        return response

    def fail_opencode(*args):
        events.append("opencode")
        raise RuntimeError("OpenCode down")

    with (
        patch.object(llm, "MODEL", "primary-model"),
        patch.object(llm, "FALLBACK_MODELS", []),
        patch.object(llm, "_openrouter_client", return_value=object()),
        patch.object(llm, "_call_openrouter", side_effect=fail_openrouter),
        patch.object(llm, "NVIDIA_NIM_API_KEY", "nim-key"),
        patch.object(llm, "_call_nvidia_nim", side_effect=fallback_nim),
        patch.object(llm, "OPENCODE_API_KEY", "zen-key"),
        patch.object(llm, "OPENCODE_MODEL", "zen-model"),
        patch.object(llm, "OPENCODE_FALLBACK_MODELS", []),
        patch.object(llm, "_call_opencode_zen", side_effect=fail_opencode),
    ):
        result = llm.chat_completion([{"role": "user", "content": "hello"}])

    assert result is response
    assert events == ["nim"]


def test_provider_quota_failure_stops_openrouter_model_retries():
    calls = []

    def quota_failure(*args):
        calls.append(args[1])
        raise RuntimeError("HTTP 429 free-models-per-day quota exceeded")

    with (
        patch.object(llm, "MODEL", "primary-model"),
        patch.object(llm, "FALLBACK_MODELS", ["fallback-a", "fallback-b"]),
        patch.object(llm, "_openrouter_client", return_value=object()),
        patch.object(llm, "_call_openrouter", side_effect=quota_failure),
        patch.object(llm, "NVIDIA_NIM_API_KEY", ""),
        patch.object(llm, "OPENCODE_API_KEY", ""),
    ):
        try:
            llm.chat_completion([{"role": "user", "content": "hello"}])
        except RuntimeError:
            pass

    assert calls == ["primary-model"]


def test_model_access_403_does_not_skip_other_models():
    error = RuntimeError("HTTP 403 model access disabled")
    assert llm._failure_scope(error) == "model"
    assert llm._failure_scope(RuntimeError("HTTP 402 insufficient account funds")) == "provider"
    assert llm._failure_scope(RuntimeError("HTTP 429 free-models-per-day")) == "provider"


def test_nvidia_nim_uses_configured_openai_compatible_endpoint_and_tools():
    response = object()
    client = MagicMock()
    client.chat.completions.create.return_value = response
    tool = {"type": "function", "function": {"name": "example", "parameters": {"type": "object"}}}

    with (
        patch.object(llm, "NVIDIA_NIM_API_KEY", "nim-key"),
        patch.object(llm, "NVIDIA_NIM_BASE_URL", "https://nim.example/v1"),
        patch.object(llm, "NVIDIA_NIM_MODEL", "example/model"),
        patch.object(llm, "OpenAI", return_value=client) as openai,
    ):
        result = llm._call_nvidia_nim([{"role": "user", "content": "hello"}], [tool])

    assert result is response
    openai.assert_called_once_with(
        base_url="https://nim.example/v1",
        api_key="nim-key",
        timeout=60.0,
    )
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "example/model"
    assert kwargs["tools"] == [tool]
    assert kwargs["tool_choice"] == "auto"
