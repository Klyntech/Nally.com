# NALLY branch reconciliation

Snapshot date: 2026-10-19  
Main snapshot inspected: `bfc34c983a9901f8291fbe0ea17fe858dedb2dea`

## Decision

Treat `main` as the authoritative source tree. Do not merge the remaining feature branches wholesale: several are divergent in Git history because changes were integrated through squash merges, while the implementation files are already identical to `main`. Compare file content and tests before transferring any branch-only change.

## Branch dependency map

| Branch | Main-relative history at snapshot | Main implementation evidence | Disposition |
| --- | ---: | --- | --- |
| `feat/law-library` | 7 ahead / 1 behind | `nally/library/store.py` matches main; its `nally/telegram/bot.py` differs from the newer composite implementation | Keep main's library store; review only bot-specific deltas |
| `feat/telegram-progress-ui` | 10 ahead / 1 behind | `nally/agent/graph.py` and `nally/telegram/bot.py` match main | Feature appears integrated; no wholesale merge |
| `feat/mcp-client-manager` | 40 ahead / 4 behind | `nally/tools/mcp_client.py` and `nally/agent/llm.py` match main | Feature appears integrated; validate permissions and failure behavior on main |
| `feat/tavily-brave-search-fallback` | 24 ahead / 5 behind | `nally/tools/web.py` matches main | Feature appears integrated; validate provider fallback on main |
| `feat/telegram-rich-rendering` | 14 ahead / 7 behind | Its bot and renderer differ from main | Do not merge wholesale; main's rendering must remain integrated with progress, library ingestion, and rich tables |
| `feat/telegram-rich-tables` | 1 ahead / 2 behind | `nally/telegram/rich.py` and `nally/telegram/telegram_renderer.py` match main | Feature appears integrated; no wholesale merge |
| `fix/persistent-memory-context` | 21 ahead / 7 behind | `nally/memory/store.py` matches main; graph and prompt differ due to later features on main | Keep main's graph/prompt composite; inspect only behavior not represented in main tests |
| `fix/telegram-inline-ui-main` | 3 ahead / 4 behind | `nally/telegram/menus.py` matches main | Feature appears integrated; no wholesale merge |

Commit counts are ancestry information, not a reliable measure of missing feature work. The content comparisons above are the more useful signal.

## Shared-module ownership

- **Agent orchestration:** `nally/agent/graph.py` is authoritative. It coordinates memory context, tool calls, direct web search, and Telegram progress events. Avoid taking an older graph wholesale from a feature branch.
- **Provider failover:** `nally/agent/llm.py` owns LLM provider ordering and model fallback; `nally/tools/web.py` owns web-search provider fallback.
- **MCP:** `nally/tools/mcp_client.py` owns discovery, allowlists, policy checks, timeouts, and remote invocation. `nally/tools/registry.py` is the single registration boundary used by the agent.
- **Persistent memory:** `nally/memory/store.py` stores durable facts and conversation turns in separate tables. `nally/tools/memory_tools.py` applies the active session context; the graph must pass the same scoped session through recall, tool calls, and turn persistence.
- **Document retrieval:** `nally/library/chunking.py`, `embeddings.py`, `ingest.py`, and `store.py` implement ingestion and retrieval. `nally/library/tools.py` exposes retrieval tools; `nally/tools/library_tools.py` re-exports them to the central registry.
- **Telegram:** `nally/telegram/bot.py` is the integration point for user authorization, document ingestion, progress updates, menus, and rich rendering. `menus.py`, `progress.py`, `telegram_renderer.py`, and `rich.py` are supporting modules, not independent replacements for the bot.
- **API security:** `nally/api/app.py` is the HTTP boundary. It must authenticate requests and derive a principal-scoped session before calling the agent.

## Integration order

1. Land and verify the fail-closed security/CI hardening PR.
2. Keep the current main implementations for library, progress UI, MCP, and web search; port only demonstrably missing behavior from stale branches.
3. Verify citation-preserving document retrieval and cross-session isolation.
4. Add MCP timeout/permission/partial-failure tests and end-to-end agent recovery tests.
5. Keep Telegram as the initial interface while testing the API as the service boundary.
6. Record the exact passing integration commit after the final CI run. A later code change invalidates that record until CI passes again.
