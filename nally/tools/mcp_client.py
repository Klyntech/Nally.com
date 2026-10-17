"""MCP client integration for configured external MCP servers.

Servers are configured explicitly through NALLY_MCP_SERVERS JSON. Only enabled
servers and explicitly allow-listed tools are exposed to the agent.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from nally.core.logging import logger

_DEFAULT_TIMEOUT = 15.0
_CACHE_TTL = 30.0
_NAME_RE = re.compile(r"[^a-zA-Z0-9_]+")


class MCPServerConfig(BaseModel):
    """Validated configuration for one external MCP server."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    transport: Literal["stdio", "streamable_http"]
    enabled: bool = False
    # Enforce provider-specific permissions after the explicit tool allowlist.
    policy: Literal["none", "github_no_delete", "read_only"] = "none"
    allowed_tools: list[str] = Field(default_factory=list)
    timeout_seconds: float = Field(default=_DEFAULT_TIMEOUT, gt=0, le=120)
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)

    def validate_transport_config(self) -> None:
        if self.transport == "stdio" and not self.command:
            raise ValueError(f"MCP server {self.name!r}: stdio transport requires command")
        if self.transport == "streamable_http" and not self.url:
            raise ValueError(f"MCP server {self.name!r}: streamable_http transport requires url")


def load_server_configs(raw: str | None = None) -> list[MCPServerConfig]:
    """Parse MCP server configuration without logging credentials."""
    value = os.getenv("NALLY_MCP_SERVERS", "[]") if raw is None else raw
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("NALLY_MCP_SERVERS must contain valid JSON") from exc
    if not isinstance(parsed, list):
        raise TypeError("NALLY_MCP_SERVERS must be a JSON array")

    configs: list[MCPServerConfig] = []
    names: set[str] = set()
    for item in parsed:
        config = MCPServerConfig.model_validate(item)
        config.validate_transport_config()
        if config.name in names:
            raise ValueError(f"Duplicate MCP server name: {config.name}")
        names.add(config.name)
        configs.append(config)
    return configs


_ENV_PLACEHOLDER_RE = re.compile(r"\$[{]([A-Z][A-Z0-9_]*)[}]")


def _resolve_env_value(value: str, *, label: str) -> str:
    """Expand environment placeholders without logging secret values."""
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        resolved = os.getenv(key)
        if resolved is None:
            raise ValueError(f"Missing environment variable {key} referenced by {label}")
        return resolved

    return _ENV_PLACEHOLDER_RE.sub(replace, value)


def _resolved_headers(config: MCPServerConfig) -> dict[str, str]:
    return {
        key: _resolve_env_value(value, label=f"server {config.name} header {key}")
        for key, value in config.headers.items()
    }


def _resolved_env(config: MCPServerConfig) -> dict[str, str]:
    return {
        key: _resolve_env_value(value, label=f"server {config.name} environment {key}")
        for key, value in config.env.items()
    }

_DESTRUCTIVE_TOOL_RE = re.compile(
    r"(?:delete|remove|destroy|purge|drop|truncate)", re.IGNORECASE
)
_READ_ONLY_TOOL_RE = re.compile(
    r"^(?:get|list|search|find|fetch|read|describe|inspect|show|query_logs|"
    r"explain|compare|whoami|health|status|retrieve|lookup)(?:_|$)",
    re.IGNORECASE,
)


def _tool_allowed_by_policy(config: MCPServerConfig, tool_name: str) -> bool:
    """Apply a fail-closed policy after the configured explicit allowlist."""
    normalized = tool_name.lower().replace("-", "_")
    if config.policy == "none":
        return True
    if config.policy == "github_no_delete":
        return _DESTRUCTIVE_TOOL_RE.search(normalized) is None
    if config.policy == "read_only":
        # Read-only access must not expose secrets or capabilities that can write data.
        if re.search(r"(?:secret|password|presign|connection_string)", normalized):
            return False
        # Arbitrary SQL execution is not read-only just because a caller intends SELECT.
        if normalized in {"run_sql", "run_sql_transaction", "execute_sql", "query"}:
            return False
        return _READ_ONLY_TOOL_RE.match(normalized) is not None
    return False


def _safe_name(value: str) -> str:
    return _NAME_RE.sub("_", value).strip("_") or "tool"


def _schema_type(schema: dict[str, Any]) -> Any:
    """Translate common JSON Schema types into Python types for tool arguments."""
    schema_type = schema.get("type")
    if "enum" in schema:
        from typing import Literal as TypingLiteral

        values = schema["enum"]
        if values and all(isinstance(value, str) for value in values):
            return TypingLiteral.__getitem__(tuple(values))
    if schema_type == "string":
        return str
    if schema_type == "integer":
        return int
    if schema_type == "number":
        return float
    if schema_type == "boolean":
        return bool
    if schema_type == "array":
        return list[_schema_type(schema.get("items", {}))]
    if schema_type == "object":
        return dict[str, Any]
    return Any


def _args_model(server_name: str, tool_name: str, schema: dict[str, Any]) -> type[BaseModel]:
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    fields: dict[str, tuple[Any, Any]] = {}
    for name, definition in properties.items():
        field_type = _schema_type(definition)
        description = definition.get("description")
        if name not in required:
            field_type = field_type | None
            default = None
        else:
            default = ...
        fields[name] = (
            field_type,
            Field(default=default, description=description),
        )
    model_name = f"MCP_{_safe_name(server_name)}_{_safe_name(tool_name)}_Args"
    return create_model(model_name, **fields)


def _run_async(coroutine: Any, timeout: float) -> Any:
    """Run an async MCP operation from sync agent code, including inside an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(asyncio.wait_for(coroutine, timeout=timeout))

    result: list[Any] = []
    failure: list[BaseException] = []

    def runner() -> None:
        try:
            result.append(asyncio.run(asyncio.wait_for(coroutine, timeout=timeout)))
        except BaseException as exc:
            failure.append(exc)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(timeout + 1)
    if thread.is_alive():
        raise TimeoutError("MCP operation exceeded its timeout")
    if failure:
        raise failure[0]
    return result[0] if result else None


def _serialize_result(result: Any) -> str:
    if getattr(result, "isError", False):
        raise RuntimeError("MCP tool returned an error")
    chunks: list[str] = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text is not None:
            chunks.append(str(text))
        else:
            chunks.append(json.dumps(item.model_dump(mode="json"), ensure_ascii=False))
    if chunks:
        return "\n".join(chunks)
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return json.dumps(structured, ensure_ascii=False)
    return ""


async def _connected_call(config: MCPServerConfig, tool_name: str, arguments: dict[str, Any]) -> str:
    """Connect, initialize, call one tool, and close all transport resources."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamablehttp_client

    async def invoke(read_stream: Any, write_stream: Any) -> str:
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments=arguments)
            return _serialize_result(result)

    if config.transport == "stdio":
        params = StdioServerParameters(
            command=config.command or "",
            args=config.args,
            env={**os.environ, **_resolved_env(config)},
        )
        async with stdio_client(params) as (read_stream, write_stream):
            return await asyncio.wait_for(
                invoke(read_stream, write_stream),
                timeout=config.timeout_seconds,
            )

    async with streamablehttp_client(config.url or "", headers=_resolved_headers(config)) as (
        read_stream,
        write_stream,
        _,
    ):
        return await asyncio.wait_for(
            invoke(read_stream, write_stream),
            timeout=config.timeout_seconds,
        )


class MCPTool:
    """Small LangChain-compatible adapter for an allow-listed MCP tool."""

    def __init__(self, config: MCPServerConfig, metadata: Any):
        self.server_config = config
        self.remote_name = metadata.name
        self.name = f"mcp__{_safe_name(config.name)}__{_safe_name(metadata.name)}"
        self.description = (
            f"MCP server {config.name}: {metadata.description or metadata.name}"
        )
        self.args_schema = _args_model(
            config.name,
            metadata.name,
            getattr(metadata, "inputSchema", None) or {"type": "object", "properties": {}},
        )

    def invoke(self, arguments: dict[str, Any]) -> str:
        if self.remote_name not in self.server_config.allowed_tools:
            raise PermissionError(f"MCP tool {self.remote_name!r} is not allow-listed")
        if not _tool_allowed_by_policy(self.server_config, self.remote_name):
            raise PermissionError(
                f"MCP policy {self.server_config.policy!r} blocks tool {self.remote_name!r}"
            )
        try:
            return _run_async(
                _connected_call(self.server_config, self.remote_name, arguments),
                timeout=self.server_config.timeout_seconds,
            )
        except TimeoutError as exc:
            raise RuntimeError(
                f"MCP tool {self.name} timed out after "
                f"{self.server_config.timeout_seconds:g}s"
            ) from exc
        except Exception as exc:
            logger.warning("MCP tool call failed server=%s tool=%s", self.server_config.name, self.remote_name)
            raise RuntimeError(f"MCP tool {self.name} failed: {type(exc).__name__}") from exc


_cached_tools: list[MCPTool] = []
_cache_expires_at = 0.0


async def _discover_server(config: MCPServerConfig) -> list[MCPTool]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamablehttp_client

    async def discover(read_stream: Any, write_stream: Any) -> list[MCPTool]:
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            response = await session.list_tools()
            discovered = []
            allowed = set(config.allowed_tools)
            for metadata in response.tools:
                if metadata.name not in allowed:
                    continue
                if not _tool_allowed_by_policy(config, metadata.name):
                    continue
                discovered.append(MCPTool(config, metadata))
            return discovered

    if config.transport == "stdio":
        params = StdioServerParameters(
            command=config.command or "",
            args=config.args,
            env={**os.environ, **_resolved_env(config)},
        )
        async with stdio_client(params) as (read_stream, write_stream):
            return await asyncio.wait_for(
                discover(read_stream, write_stream),
                timeout=config.timeout_seconds,
            )

    async with streamablehttp_client(config.url or "", headers=_resolved_headers(config)) as (
        read_stream,
        write_stream,
        _,
    ):
        return await asyncio.wait_for(
            discover(read_stream, write_stream),
            timeout=config.timeout_seconds,
        )


def get_mcp_tools(*, refresh: bool = False) -> list[MCPTool]:
    """Return tools from enabled servers, refreshing discovery at most every 30s."""
    global _cached_tools, _cache_expires_at
    now = time.monotonic()
    if not refresh and now < _cache_expires_at:
        return list(_cached_tools)

    discovered: list[MCPTool] = []
    try:
        configs = load_server_configs()
    except Exception:
        logger.exception("Invalid NALLY_MCP_SERVERS configuration")
        return []

    for config in configs:
        if not config.enabled or not config.allowed_tools:
            continue
        try:
            discovered.extend(_run_async(_discover_server(config), timeout=config.timeout_seconds))
        except Exception as exc:
            logger.warning(
                "MCP discovery failed server=%s error=%s",
                config.name,
                type(exc).__name__,
            )

    _cached_tools = discovered
    _cache_expires_at = now + _CACHE_TTL
    return list(discovered)


def reset_mcp_tool_cache() -> None:
    """Clear discovery cache; primarily useful in tests and controlled reloads."""
    global _cached_tools, _cache_expires_at
    _cached_tools = []
    _cache_expires_at = 0.0
