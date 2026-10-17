# Nally.com

Greenfield personal AI assistant.

- **LLM:** OpenRouter (`nvidia/nemotron-3.5-lightning:free`)
- **Agent:** Simple LangGraph ReAct with hard limits
- **Memory:** Postgres from day 1
- **Tools:** `memory_*`, `run_command`, `file_*`
- **Telegram:** webhook (Render) or polling (local)

## Web search

`web_search` tries providers in this order: Tavily, Brave Search, then DuckDuckGo. Set `TAVILY_API_KEY` and `BRAVE_SEARCH_API_KEY` in `.env`; DuckDuckGo is used without a key when the API providers are unavailable or return no usable results. Each provider request has an 8-second timeout, with a shared 18-second search budget that reduces the timeout for later providers. Explicit standalone requests such as `Search for ...` bypass the LLM round trip. The `fetch` tool remains separate and retrieves a selected URL.

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
