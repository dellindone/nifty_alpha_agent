## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

---

## Project: Nifty Alpha Agent

Standalone live trading agent for NIFTY 50 options on NSE. Fully isolated —
no shared code with banknifty or sensex agents.

### Entrypoint
```
python main.py --live      # live trading
python main.py --replay --date 2026-05-04
```

### Module ownership — read only what you need

| Task | File to read |
|------|-------------|
| Tick / WebSocket / subscriptions | `live_engine/tick_handler.py` |
| Terminal display | `live_engine/display.py` |
| Signal → pending → entry routing | `live_engine/signal_router.py` |
| EOD close, heartbeat, schedule | `live_engine/eod_handler.py` |
| Candle poll, frame fetch, daily P&L | `live_engine/candle_poll.py` |
| Main loop, init, sleep | `live_engine/engine.py` |
| Trade lifecycle, fills, SL/trail/exit | `live_engine/live_mode.py` |
| Parquet + DB persistence | `live_engine/lib/journal.py` |
| Telegram alerts | `live_engine/lib/reporter.py` |
| Entry signal filtering | `live_engine/lib/signal_handler.py` |
| DB schema + upsert | `live_engine/db.py` |
| Capital tracking | `live_engine/risk/capital_tracker.py` |
| Signal thresholds, risk params | `live_engine/config/settings.py` |
| Symbol, lot size, strike spacing | `live_engine/config/instruments.py` |

### Never read engine.py to fix a bug
`engine.py` only wires helpers together. Bugs are always in the specific helper file above.

### Key rules
- File size limit: **120 lines max** — split if exceeded
- Config is single source of truth: `live_engine/config/settings.py`
- Credentials: `.env` file at agent root — never hardcode
- Models: `models/` directory at agent root
- Imports: `from config.settings import ...` (live_engine/ is on sys.path)

### Workflow: ChatGPT + Claude
- ChatGPT writes code → Claude reviews
- Start each Claude session with: "Nifty alpha agent — check memory for context. Working on [task]."
