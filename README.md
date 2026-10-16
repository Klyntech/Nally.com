# Nally.com

Greenfield personal AI assistant.

- **LLM:** OpenRouter (`nvidia/nemotron-3.5-lightning:free`)
- **Agent:** Simple LangGraph ReAct with hard limits
- **Memory:** Postgres from day 1
- **Tools:** `memory_*`, `run_command`, `file_read` / `file_write` / `file_list`

## Quick start

```bash
cp .env.example .env
# set OPENROUTER_API_KEY, DATABASE_URL, NALLY_ACCESS_TOKEN

pip install -r requirements.txt
python main.py
```

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
  api/       FastAPI
  agent/     LangGraph + OpenRouter
  tools/     memory, shell, file_io
  memory/    Postgres store
  core/      logging
```
