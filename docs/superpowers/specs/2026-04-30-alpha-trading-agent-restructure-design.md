# Alpha Trading Agent Restructure — Design Spec

**Date:** 2026-04-30
**Status:** Approved

## Problem

The current `trading_agent` repo runs NIFTY, BANKNIFTY, and SENSEX from a shared codebase. All three indices share credentials, option chain logic, display system, and config. This causes conflicts when running agents simultaneously and makes independent VM deployment impossible.

## Goals

1. Full code isolation — no shared imports between agents
2. Each agent deployable to its own VM as a self-contained folder
3. Centralized research and backtesting workspace separate from live agents
4. Backtesting results persisted forever, never overwritten, keyed by model + date
5. `trading_agent` stays live and untouched during migration

---

## Top-Level Layout

```
chartflix/
├── trading_agent/              # existing repo — untouched, stays live during migration
├── alpha_trading_agent/        # parent directory only — NOT a git repo
│   ├── nifty_alpha_agent/      # git repo 1
│   ├── banknifty_alpha_agent/  # git repo 2
│   └── sensex_alpha_agent/     # git repo 3
└── trading_research/           # git repo — research, backtests, training pipelines
    ├── nifty/
    │   ├── backtests/
    │   ├── experiments/
    │   └── pipelines/
    ├── banknifty/
    │   ├── backtests/
    │   ├── experiments/
    │   └── pipelines/
    └── sensex/
        ├── backtests/
        ├── experiments/
        └── pipelines/
```

---

## Per-Agent Structure

Each agent is **identical in shape, different in content**. Full code redundancy is intentional — no cross-agent imports, ever.

```
nifty_alpha_agent/              # git repo
├── .venv/                      # per-agent Python environment
├── live_engine/                # all runtime Python modules
│   ├── config/
│   │   ├── settings.py         # index-specific thresholds and risk params
│   │   └── instruments.py      # symbol, lot size, strike spacing
│   ├── features/               # feature engineering (~10 files)
│   ├── ingestion/              # fyers_client.py, option_chain.py, multi_tf_builder.py, brokers/, etc.
│   ├── model/                  # predict.py, calibrator.py
│   ├── risk/                   # capital_tracker.py, position_sizer.py
│   ├── strategy/               # strike_selector.py
│   ├── utils/                  # charge_calculator, liquidity_checker, market_calendar,
│   │                           # slippage_estimator, symbol_converter
│   ├── lib/
│   │   ├── journal.py          # Parquet + DB persistence
│   │   ├── reporter.py         # Telegram alerts
│   │   └── signal_handler.py   # entry signal filtering
│   ├── db.py                   # SQLite schema + upsert
│   ├── engine.py               # main loop, init, sleep
│   ├── candle_poll.py          # frame fetch, daily P&L
│   ├── display.py              # terminal display
│   ├── eod_handler.py          # EOD close, heartbeat, schedule
│   ├── shadow_mode.py          # trade lifecycle, SL/trail/exit
│   ├── signal_router.py        # signal → pending → entry routing
│   └── tick_handler.py         # WebSocket, subscriptions
├── models/                     # prod model files e.g. NIFTY_direction.joblib
├── data/                       # market data cache
├── tokens/                     # fyers access_token file — gitignored
├── logs/
├── deploy/
│   └── nifty_alpha_agent.service   # systemd unit template for VM deployment
├── .env                        # FYERS_CLIENT_ID, FYERS_SECRET, TELEGRAM_TOKEN — gitignored
├── main.py                     # entrypoint — adds live_engine/ to sys.path
└── requirements.txt
```

Same structure applies to `banknifty_alpha_agent/` and `sensex_alpha_agent/` with their own symbols, thresholds, credentials, and models.

### Import convention

`main.py` adds `live_engine/` to `sys.path`. All internal imports use:
```python
from config.settings import Equity, Risk
from ingestion.fyers_client import FyersClient
```
No `live_engine.` prefix needed anywhere. Matches current import style exactly — zero refactoring of internal imports.

---

## Credentials Isolation

- Each agent has its own `.env` file with its own Fyers API credentials
- Fyers access token written to `tokens/` inside the agent folder
- No shared token files between agents
- `.env` and `tokens/` are gitignored in each repo

---

## Backtesting Results

All backtesting lives in `trading_research/`. Results are **never overwritten**.

```
trading_research/
└── nifty/
    └── backtests/
        └── run_20260430_143000/
            ├── results.parquet     # trade-by-trade results
            └── meta.json           # model_name, version, params, metrics, date
```

`meta.json` schema:
```json
{
  "index": "NIFTY",
  "model_name": "NIFTY_direction_v5_rr15",
  "run_date": "2026-04-30T14:30:00",
  "params": {},
  "metrics": {
    "win_rate": 0.0,
    "avg_rr": 0.0,
    "total_trades": 0
  }
}
```

Training pipelines (`train_model.py`, `build_dataset.py`, `weekly_retrain.py`) move from `trading_agent/pipelines/` to `trading_research/{index}/pipelines/`.

---

## Git Strategy

| Repo | Location | Purpose |
|------|----------|---------|
| `nifty_alpha_agent` | `alpha_trading_agent/nifty_alpha_agent/` | Live NIFTY agent |
| `banknifty_alpha_agent` | `alpha_trading_agent/banknifty_alpha_agent/` | Live BANKNIFTY agent |
| `sensex_alpha_agent` | `alpha_trading_agent/sensex_alpha_agent/` | Live SENSEX agent |
| `trading_research` | `chartflix/trading_research/` | Research, backtests, pipelines |

`alpha_trading_agent/` is a plain directory — not a git repo. Each agent has independent history.

---

## VM Deployment

Each agent folder is self-contained. To deploy to a VM:

```bash
rsync -av --exclude='.venv' --exclude='data' --exclude='logs' --exclude='tokens' \
  nifty_alpha_agent/ user@vm-nifty:/opt/nifty_alpha_agent/

# On VM:
cd /opt/nifty_alpha_agent && python -m venv .venv && pip install -r requirements.txt
cp deploy/nifty_alpha_agent.service /etc/systemd/system/
systemctl enable --now nifty_alpha_agent
```

---

## Migration Order

1. Build `nifty_alpha_agent` — copy from `trading_agent`, adapt structure, validate live
2. Build `banknifty_alpha_agent` — copy from nifty alpha, adapt logic and config
3. Build `sensex_alpha_agent` — copy from nifty alpha, adapt logic and config
4. Build `trading_research` — migrate pipelines, experiments, research scripts
5. Archive `trading_agent` once all three alpha agents are validated live

`trading_agent` remains live and untouched throughout steps 1–4.

---

## What Does NOT Go in Alpha Agents

| Item | Goes to |
|------|---------|
| `pipelines/train_model.py` | `trading_research/{index}/pipelines/` |
| `pipelines/build_dataset.py` | `trading_research/{index}/pipelines/` |
| `pipelines/weekly_retrain.py` | `trading_research/{index}/pipelines/` |
| `scripts/simulate_*.py` | `trading_research/{index}/experiments/` |
| `research/` | `trading_research/` |
| `experiments/` | `trading_research/{index}/experiments/` |
| `agents/nifty/multi_engine.py` | deleted — replaced by separate alpha agents |
| `agents/nifty/multi_display.py` | deleted — each agent has its own display |
