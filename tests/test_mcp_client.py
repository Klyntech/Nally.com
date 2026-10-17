from __future__ import annotations

from types import SimpleNamespace

import pytest

from nally.tools.mcp_client import (
    MCPTool,
    get_mcp_tools,
    load_server_configs,
    reset_mcp_tool_cache,
)


def test_server_config_requires_transport_details() -> None:
    with pytest.raises(ValueError, match="requires command"):
        load_server_configs(
            '[{"name":"local","transport":"stdio","enabled":true,"allowed_tools":["x"]}]'
        )
    with pytest.raises(ValueError, match="requires url"):
        load_server_configs(
            '[{"name":"remote","transport":"streamable_http","enabled":true,"allowed_tools":["x"]}]'
        )


def test_server_config_rejects_duplicate_names() -> None:
    raw = (
        '[{"name":"docs","transport":"stdio","command":"uvx"},'
        '{"name":"docs","transport":"stdio","command":"uvx"}]'
    )
    with pytest.raises(ValueError, match="Duplicate MCP server name"):
        load_server_configs(raw)


def test_server_config_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError):
        load_server_configs(
            '[{"name":"docs","transport":"stdio","command":"uvx","secret":"oops"}]'
        )


def test_invalid_json_is_reported_without_leaking_config() -> None:
    with pytest.raises(ValueError, match="valid JSON"):
        load_server_configs("not-json")


def test_mcp_tool_uses_safe_names_and_remote_argument_schema() -> None:
    config = load_server_configs(
        '[{"name":"docs server","transport":"stdio","command":"uvx","enabled":true,'
        '"allowed_tools":["search/docs"]}]'
    )[0]
    metadata = SimpleNamespace(
        name="search/docs",
        description="Search the documentation",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text to search"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
    )

    tool = MCPTool(config, metadata)

    assert tool.name == "mcp__docs_server__search_docs"
    assert "Search the documentation" in tool.description
    assert tool.args_schema.model_json_schema()["required"] == ["query"]
    parsed = tool.args_schema.model_validate({"query": "MCP"})
    assert parsed.query == "MCP"
    assert parsed.limit is None


def test_mcp_tools_are_not_discovered_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_mcp_tool_cache()
    monkeypatch.setenv(
        "NALLY_MCP_SERVERS",
        '[{"name":"docs","transport":"stdio","command":"uvx","enabled":false,'
        '"allowed_tools":["search_docs"]}]',
    )

    assert get_mcp_tools(refresh=True) == []

    reset_mcp_tool_cache()


def test_mcp_tools_are_not_discovered_without_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_mcp_tool_cache()
    monkeypatch.setenv(
        "NALLY_MCP_SERVERS",
        '[{"name":"docs","transport":"stdio","command":"uvx","enabled":true,'
        '"allowed_tools":[]}]',
    )

    assert get_mcp_tools(refresh=True) == []

    reset_mcp_tool_cache()

def test_environment_placeholders_resolve_without_changing_literal_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nally.tools.mcp_client import _resolve_env_value

    monkeypatch.setenv("MCP_TEST_TOKEN", "test-secret-value")

    assert _resolve_env_value(
        "Bearer ${MCP_TEST_TOKEN}", label="test header"
    ) == "Bearer test-secret-value"
    assert _resolve_env_value("plain-value", label="test header") == "plain-value"


def test_missing_environment_placeholder_fails_closed() -> None:
    from nally.tools.mcp_client import _resolve_env_value

    with pytest.raises(ValueError, match="Missing environment variable MCP_MISSING_TOKEN"):
        _resolve_env_value("${MCP_MISSING_TOKEN}", label="test header")
