from unittest.mock import MagicMock, patch

from nally.agent import llm


def test_nvidia_nim_is_last_provider_after_openrouter_and_opencode():
    events = []
    response = object()

    with (
        patch.object(llm, "MODEL", "primary-model"),
        patch.object(llm, "FALLBACK_MODELS", []),
        patch.object(llm, "_openrouter_client", return_value=object()),
        patch.object(llm, "_call_openrouter", side_effect=lambda *args: (_ for _ in ()).throw(RuntimeError("OpenRouter down"))),
        patch.object(llm, "OPENCODE_API_KEY", "zen-key"),
        patch.object(llm, "OPENCODE_MODEL", "zen-model"),
        patch.object(llm, "OPENCODE_FALLBACK_MODELS", []),
        patch.object(llm, "_call_opencode_zen", side_effect=lambda *args: (events.append("opencode"), (_ for _ in ()).throw(RuntimeError("OpenCode down"))[1]),
        patch.object(llm, "NVIDIA_NIM_API_KEY", "nim-key"),
        patch.object(llm, "_call_nvidia_nim", side_effect=lambda *args: (events.append("nim"), response)[1]),
    ):
        result = llm.chat_completion([{"role": "user", "content": "hello"}])

    assert result is response
    assert events[-1] == "nim"
    assert events.count("opencode") == 6


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
