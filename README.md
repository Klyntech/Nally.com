# Nally.com

Greenfield personal AI assistant.

- **LLM fallback order:** OpenRouter model fallbacks, OpenCode Zen, then NVIDIA NIM as the last resort (`deepseek-ai/deepseek-v4-flash` by default)
- **Agent:** Simple LangGraph ReAct with hard limits
- **Memory:** Postgres from day 1
- **Tools:** `memory_*`, `run_command`, `file_*`
- **Telegram:** webhook (Render) or polling (local)

## LLM provider fallback

Nally tries providers in this order: OpenRouter and its configured model fallbacks, OpenCode Zen and its model fallbacks, then NVIDIA NIM as the final fallback. Providers without configured API keys are skipped. Configure `NVIDIA_NIM_API_KEY` to enable the last resort; `NVIDIA_NIM_BASE_URL` defaults to `https://integrate.api.nvidia.com/v1`, and `NVIDIA_NIM_MODEL` defaults to `deepseek-ai/deepseek-v4-flash`. NIM uses an OpenAI-compatible chat-completions API, including tool calling where supported by the selected model. This does not change the primary provider.

## Web search

`web_search` tries providers in this order: Tavily, Brave Search, then DuckDuckGo. Set `TAVILY_API_KEY` and `BRAVE_SEARCH_API_KEY` in `.env`; DuckDuckGo is used without a key when the API providers are unavailable or return no usable results. Each provider request has an 8-second timeout, with a shared 18-second search budget that reduces the timeout for later providers. Explicit standalone requests such as `Search for ...` bypass the LLM round trip. The `fetch` tool remains separate and retrieves a selected URL.

## MCP client

Nally can consume tools from explicitly configured MCP servers. MCP is opt-in:
servers are disabled unless `enabled` is true, and a server exposes only the
tool names listed in `allowed_tools`. Provider policies are enforced during
discovery and again immediately before invocation. Supported transports are local `stdio`
and remote Streamable HTTP. Each discovery or tool call has a configurable
timeout (maximum 120 seconds); failed discovery does not stop built-in tools.

Set `NALLY_MCP_SERVERS` to a JSON array in `.env`. Example:

```json
[
  {
    "name": "docs",
    "transport": "stdio",
    "enabled": true,
    "policy": "read_only",
    "command": "uvx",
    "args": ["example-mcp-server"],
    "allowed_tools": ["search_docs"],
    "timeout_seconds": 15
  }
]
```

For remote servers, set `"transport": "streamable_http"` and `"url"`. Header
and stdio environment values support environment placeholders such as
`${GITHUB_MCP_TOKEN}`; Nally resolves them at runtime and fails closed when a
referenced variable is missing. Keep credentials in environment variables, not
committed JSON.

Example provider configuration for the permissions requested:

```json
[
  {
    "name": "github",
    "transport": "streamable_http",
    "enabled": true,
    "policy": "github_no_delete",
    "url": "https://api.githubcopilot.com/mcp/",
    "headers": {"Authorization": "Bearer ${GITHUB_MCP_TOKEN}"},
    "allowed_tools": ["*"],
    "timeout_seconds": 30
  },
  {
    "name": "neon",
    "transport": "streamable_http",
    "enabled": true,
    "policy": "read_only",
    "url": "https://mcp.neon.tech/mcp?readonly=true",
    "headers": {"Authorization": "Bearer ${NEON_API_KEY}"},
    "allowed_tools": ["*"],
    "timeout_seconds": 30
  }
]
```

Put that JSON in `NALLY_MCP_SERVERS` in the deployment environment. This enables
GitHub's discovered tools except destructive-name operations, and Neon tools
classified as read-only. The local policy blocks obvious destructive tools, but
provider-side least-privilege credentials remain important: name-based filtering
cannot guarantee that a remote server's misleadingly named tool has no side effects.

Initial integration targets:

- **GitHub:** `https://api.githubcopilot.com/mcp/`. Use `policy: "github_no_delete"`
  with `allowed_tools: ["*"]` to expose every discovered tool except delete/remove/destroy/purge/drop/truncate operations.
  The current manager supports bearer-token authentication; its hosted OAuth browser
  flow is not implemented yet.
- **Render:** `https://mcp.render.com/mcp`. Use a Render API key in the
  Authorization header. Its MCP server includes deployment and environment
  variable changes, so only allowlist the operations you intend Nally to use.
- **Neon:** `https://mcp.neon.tech/mcp?readonly=true` and `policy: "read_only"`.
  Use `allowed_tools: ["*"]` with the local `read_only` policy to expose recognized
  read-oriented tool names while blocking arbitrary SQL execution and mutation tools. Also use an API key in the Authorization
  header. Neon OAuth is not yet supported by Nally's manager.
- **Twelve Data:** the hosted `https://mcp.twelvedata.com/mcp` endpoint uses
  OAuth, which Nally's manager does not yet implement. Use Twelve Data's local
  stdio server with `TWELVE_DATA_API_KEY` for now.

Normally tool names must be explicitly listed in `allowed_tools`. For the requested
provider-wide access, `allowed_tools: ["*"]` is accepted only with `github_no_delete`
or `read_only`: GitHub exposes discovered tools except destructive names, while Neon
exposes only recognized read-oriented tools. Wildcards are ignored with `policy: "none"`.
The read-only policy blocks SQL execution and sensitive secret/presign operations. The remote server must also be configured
with least-privilege credentials because local policy cannot control side effects
hidden behind a misleading tool name. Treat server commands, URLs,
and headers as trusted administrator configuration.

## Quick start

```bash
cp .env.example .env
# set OPENROUTER_API_KEY, DATABASE_URL, NALLY_ACCESS_TOKEN, TELEGRAM_BOT_TOKEN

pip install -r requirements.txt
python main.py
```

### Telegram

**Production (webhook)**

```bash
TELEGRAM_MODE=webhook
NALLY_BASE_URL=https://your-service.onrender.com
TELEGRAM_BOT_TOKEN=123:ABC
TELEGRAM_USER_ID=your_numeric_id
```

Webhook path: `POST /telegram/webhook` (set automatically on startup).

**Local (polling)**

```bash
TELEGRAM_MODE=polling
TELEGRAM_BOT_TOKEN=123:ABC
```

> Note: polling needs a PTB updater. Prefer webhook on Render.

### HTTP API

```bash
curl -s localhost:10000/health
curl -s -X POST localhost:10000/v1/chat \
  -H "Authorization: Bearer $NALLY_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"Remember my name is Clinton"}'
```

## Limits (defaults)

| Limit | Value |
|-------|-------|
| Max iterations | 12 |
| Max tool calls | 20 |
| Wall time | 90s |
| Command timeout | 30s |

## Layout

```
nally/
  api/         FastAPI + webhook
  agent/       LangGraph + OpenRouter
  telegram/    Bot handlers
  tools/       memory, shell, file_io
  memory/      Postgres
```
