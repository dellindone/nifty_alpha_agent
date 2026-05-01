# Nifty Alpha Agent — Scaffold & Adapt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a fully self-contained `nifty_alpha_agent/` git repo under `chartflix/alpha_trading_agent/` — isolated from all other agents, deployable to a standalone VM.

**Architecture:** Copy all live-runtime files from `trading_agent/` into a flat `live_engine/` folder. Fix all internal imports (strip `core.` and `agents.nifty.` prefixes via sed). Add a clean `main.py` that puts `live_engine/` on `sys.path` so existing import names work unchanged. `settings.py` already resolves paths relative to `__file__` — `parents[2]` will naturally point to `nifty_alpha_agent/` once the file moves there.

**Tech Stack:** Python 3.11+, fyers-apiv3, scikit-learn/xgboost, SQLAlchemy, python-dotenv, systemd (for VM deployment)

**Note on scope:** This is Plan 1 of 4. Plans 2–4 (banknifty_alpha_agent, sensex_alpha_agent, trading_research) follow once this agent is validated live. Those plans will copy nifty_alpha_agent as their starting point.

---

## File Map

### Created from scratch
- `chartflix/alpha_trading_agent/nifty_alpha_agent/main.py` — entrypoint, sets sys.path
- `chartflix/alpha_trading_agent/nifty_alpha_agent/requirements.txt` — nifty-only deps (no BTC/growwapi)
- `chartflix/alpha_trading_agent/nifty_alpha_agent/.env.example` — credential template
- `chartflix/alpha_trading_agent/nifty_alpha_agent/.gitignore`
- `chartflix/alpha_trading_agent/nifty_alpha_agent/deploy/nifty_alpha_agent.service` — systemd unit

### Copied then adapted
- `live_engine/config/settings.py` — strip BTC class, remove other-index entries, remove EXPERIMENTS/PIPELINES paths
- `live_engine/ingestion/fyers_client.py` — explicit dotenv_path pointing to agent root `.env`

### Copied verbatim (from `trading_agent/`)
All other `live_engine/` files — imports fixed by sed in Task 3, no manual edits needed.

### Folder structure created
```
nifty_alpha_agent/
├── .venv/
├── live_engine/
│   ├── base/           ← core/base/
│   ├── config/         ← core/config/
│   ├── features/       ← core/features/  (build_dataset.py excluded — training only)
│   ├── ingestion/      ← core/ingestion/ (includes brokers/ subfolder)
│   ├── model/          ← core/model/     (train.py, research.py, promoter.py excluded)
│   ├── risk/           ← core/risk/
│   ├── strategy/       ← core/strategy/
│   ├── utils/          ← core/utils/
│   ├── lib/            ← agents/nifty/lib/
│   ├── db.py           ← core/db.py
│   ├── engine.py       ← agents/nifty/engine.py
│   ├── candle_poll.py  ← agents/nifty/candle_poll.py
│   ├── display.py      ← agents/nifty/display.py
│   ├── eod_handler.py  ← agents/nifty/eod_handler.py
│   ├── shadow_mode.py  ← agents/nifty/shadow_mode.py
│   ├── signal_router.py← agents/nifty/signal_router.py
│   └── tick_handler.py ← agents/nifty/tick_handler.py
├── models/             ← models/prod/nifty_alpha_agent_model/ (prod models)
├── data/               (empty, created at runtime)
├── tokens/             (empty, fyers token written here at runtime)
├── logs/               (empty, created at runtime)
├── deploy/
├── .env.example
├── .gitignore
├── main.py
└── requirements.txt
```

---

## Task 1: Create folder skeleton and initialize git repo

**Files:**
- Create: `chartflix/alpha_trading_agent/nifty_alpha_agent/` (entire tree)

- [ ] **Step 1: Create folder structure**

Run from `chartflix/`:
```bash
mkdir -p alpha_trading_agent/nifty_alpha_agent/live_engine/{base,config,features,ingestion/brokers,model,risk,strategy,utils,lib}
mkdir -p alpha_trading_agent/nifty_alpha_agent/{models,data,tokens,logs,deploy}
```

- [ ] **Step 2: Initialize git repo**

```bash
cd alpha_trading_agent/nifty_alpha_agent
git init
git branch -M main
```

- [ ] **Step 3: Verify structure**

```bash
find . -type d | sort
```
Expected output should contain: `./live_engine`, `./live_engine/base`, `./live_engine/config`, `./live_engine/features`, `./live_engine/ingestion`, `./live_engine/ingestion/brokers`, `./live_engine/model`, `./live_engine/risk`, `./live_engine/strategy`, `./live_engine/utils`, `./live_engine/lib`, `./models`, `./data`, `./tokens`, `./logs`, `./deploy`

---

## Task 2: Copy files from trading_agent into live_engine

**Files:**
- Copy from `trading_agent/core/` and `trading_agent/agents/nifty/` into `live_engine/`

Run all copy commands from `chartflix/`:

- [ ] **Step 1: Copy core subdirectories**

```bash
DEST=alpha_trading_agent/nifty_alpha_agent/live_engine
SRC=trading_agent/core

cp $SRC/base/__init__.py $SRC/base/journal.py $SRC/base/reporter.py $DEST/base/

cp $SRC/config/__init__.py $SRC/config/settings.py $SRC/config/instruments.py $DEST/config/

# features — exclude build_dataset.py (training only, goes to trading_research)
cp $SRC/features/__init__.py \
   $SRC/features/candlestick.py \
   $SRC/features/engineering.py \
   $SRC/features/indicators.py \
   $SRC/features/institutional_context.py \
   $SRC/features/labels.py \
   $SRC/features/option_features.py \
   $SRC/features/pattern_context.py \
   $SRC/features/regime.py \
   $SRC/features/session_features.py \
   $SRC/features/vix_features.py \
   $DEST/features/

# ingestion — copy brokers/ subfolder too
cp $SRC/ingestion/__init__.py \
   $SRC/ingestion/fyers_client.py \
   $SRC/ingestion/multi_tf_builder.py \
   $SRC/ingestion/option_chain.py \
   $SRC/ingestion/option_premium_history.py \
   $SRC/ingestion/synthetic_premium.py \
   $DEST/ingestion/
cp $SRC/ingestion/brokers/__init__.py \
   $SRC/ingestion/brokers/base.py \
   $SRC/ingestion/brokers/dhan.py \
   $SRC/ingestion/brokers/factory.py \
   $SRC/ingestion/brokers/fyers.py \
   $DEST/ingestion/brokers/

# model — exclude train.py, research.py, promoter.py (training only)
cp $SRC/model/__init__.py \
   $SRC/model/calibrator.py \
   $SRC/model/predict.py \
   $DEST/model/

cp $SRC/risk/__init__.py $SRC/risk/capital_tracker.py $SRC/risk/position_sizer.py $DEST/risk/
cp $SRC/strategy/__init__.py $SRC/strategy/strike_selector.py $DEST/strategy/
cp $SRC/utils/__init__.py \
   $SRC/utils/charge_calculator.py \
   $SRC/utils/liquidity_checker.py \
   $SRC/utils/market_calendar.py \
   $SRC/utils/slippage_estimator.py \
   $SRC/utils/symbol_converter.py \
   $DEST/utils/

# db.py at live_engine root
cp $SRC/db.py $DEST/db.py
```

- [ ] **Step 2: Copy nifty agent files**

```bash
DEST=alpha_trading_agent/nifty_alpha_agent/live_engine
SRC=trading_agent/agents/nifty

# engine files — exclude multi_engine.py and multi_display.py (replaced by separate agents)
cp $SRC/engine.py \
   $SRC/candle_poll.py \
   $SRC/display.py \
   $SRC/eod_handler.py \
   $SRC/shadow_mode.py \
   $SRC/signal_router.py \
   $SRC/tick_handler.py \
   $DEST/

cp $SRC/lib/__init__.py \
   $SRC/lib/journal.py \
   $SRC/lib/reporter.py \
   $SRC/lib/signal_handler.py \
   $DEST/lib/
```

- [ ] **Step 3: Copy prod models**

```bash
cp -r trading_agent/models/prod/nifty_alpha_agent_model/. \
      alpha_trading_agent/nifty_alpha_agent/models/
```

- [ ] **Step 4: Verify all files are present**

```bash
find alpha_trading_agent/nifty_alpha_agent/live_engine -name "*.py" | sort
```

Expected: engine.py, candle_poll.py, display.py, eod_handler.py, shadow_mode.py, signal_router.py, tick_handler.py, db.py, and all files inside base/, config/, features/, ingestion/, ingestion/brokers/, model/, risk/, strategy/, utils/, lib/

---

## Task 3: Fix all imports via sed

All files currently use `from core.X import Y` and `from agents.nifty.lib.X import Y`. Since `live_engine/` will be on `sys.path`, these must become `from X import Y` and `from lib.X import Y`.

**Files:**
- Modify: all `*.py` in `live_engine/`

- [ ] **Step 1: Write a validation test first (run before sed)**

```bash
cd alpha_trading_agent/nifty_alpha_agent
grep -r "from core\." live_engine/ --include="*.py" | wc -l
grep -r "from agents\.nifty\." live_engine/ --include="*.py" | wc -l
```

Note the counts. After sed, both should be 0.

- [ ] **Step 2: Fix `agents.nifty.lib.` imports first (must run before the broader nifty rule)**

```bash
find live_engine/ -name "*.py" -exec sed -i '' 's/from agents\.nifty\.lib\./from lib./g' {} \;
```

- [ ] **Step 3: Fix `agents.nifty.` imports**

```bash
find live_engine/ -name "*.py" -exec sed -i '' 's/from agents\.nifty\./from /g' {} \;
```

- [ ] **Step 4: Fix `from core.` imports**

```bash
find live_engine/ -name "*.py" -exec sed -i '' 's/from core\./from /g' {} \;
```

- [ ] **Step 5: Verify zero remaining old-style imports**

```bash
grep -r "from core\." live_engine/ --include="*.py"
grep -r "from agents\.nifty\." live_engine/ --include="*.py"
```

Both commands must produce no output.

- [ ] **Step 6: Commit**

```bash
git add live_engine/ models/
git commit -m "feat: copy live_engine from trading_agent and fix imports"
```

---

## Task 4: Adapt settings.py for nifty-only

Remove BTC class, other-index entries in DATA_DIRS/MODEL_DIRS, EXPERIMENTS/PIPELINES paths, and training-only Model class. Keep all NIFTY-specific config.

**Files:**
- Modify: `live_engine/config/settings.py`

- [ ] **Step 1: Write validation test**

Create `live_engine/config/test_settings.py`:
```python
def test_paths_root_is_agent_dir():
    from pathlib import Path
    from config.settings import Paths
    assert Paths.ROOT.name == "nifty_alpha_agent", f"Expected nifty_alpha_agent, got {Paths.ROOT.name}"

def test_no_btc_in_data_dirs():
    from config.settings import Paths
    assert "btc" not in Paths.DATA_DIRS

def test_nifty_in_data_dirs():
    from config.settings import Paths
    assert "nifty" in Paths.DATA_DIRS

def test_nifty_instrument_config():
    from config.settings import INSTRUMENT_CONFIGS
    assert "NIFTY" in INSTRUMENT_CONFIGS
    assert "BANKNIFTY" not in INSTRUMENT_CONFIGS
    assert "SENSEX" not in INSTRUMENT_CONFIGS
```

- [ ] **Step 2: Run test to verify it fails (Paths.ROOT will be wrong until we set up .venv)**

Skip running the test now — we'll run it in Task 10 after venv setup. Proceed to implementation.

- [ ] **Step 3: Edit settings.py**

Open `live_engine/config/settings.py` and make these changes:

**Remove the entire `BTC` class** (lines ~49–91 in original).

**Replace `Paths` class** with:
```python
class Paths:
    ROOT   = Path(__file__).resolve().parents[2]
    DATA   = ROOT / "data"
    MODELS = ROOT / "models"
    LOGS   = ROOT / "logs"

    DATA_DIRS = {
        "nifty": DATA / "nifty",
    }

    MODEL_DIRS = {
        "nifty": MODELS,
    }
```

**Replace `INSTRUMENT_CONFIGS`** with nifty-only:
```python
INSTRUMENT_CONFIGS: dict[str, InstrumentConfig] = {
    "NIFTY": InstrumentConfig(
        min_confidence=0.55,
        min_rr=1.2,
        max_trades_per_day=6,
        daily_target=6_000,
        abs_sl_max=9999,
        atr_mult_scale=1.25,
        trail_width_mult=0.5,
        trail_activation_rr=1.0,
    ),
}
```

**Replace `Logging` class** with:
```python
class Logging:
    LEVEL             = os.getenv("LOG_LEVEL", "INFO")
    FILE_NIFTY        = Paths.LOGS / "shadow_nifty.log"
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
```

**Remove `Model` class entirely** (training-only).

- [ ] **Step 4: Commit**

```bash
git add live_engine/config/settings.py
git commit -m "feat: adapt settings.py for nifty-only alpha agent"
```

---

## Task 5: Create main.py

**Files:**
- Create: `nifty_alpha_agent/main.py`

- [ ] **Step 1: Create main.py**

```python
"""Nifty Alpha Agent — entrypoint.

Usage:
    python main.py --shadow          # paper trade, no real orders
    python main.py --live            # live trading
    python main.py --shadow --dry-run  # shadow mode, log only
"""
import argparse
import logging
import sys
from pathlib import Path

# Add live_engine/ to sys.path so all internal imports resolve without prefix.
sys.path.insert(0, str(Path(__file__).parent / "live_engine"))


def _setup_logging(verbose: bool) -> None:
    from config.settings import Paths
    Paths.LOGS.mkdir(parents=True, exist_ok=True)
    log_file = Paths.LOGS / "agent.log"
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    sys.stderr = open(log_file, "a", encoding="utf-8", buffering=1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Nifty Alpha Agent")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--shadow", action="store_true", help="Paper trade")
    mode.add_argument("--live",   action="store_true", help="Live trading")
    parser.add_argument("--dry-run", action="store_true", help="Log only, no orders")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    from config.settings import Paths
    from engine import Engine

    Paths.DATA_DIRS["nifty"].mkdir(parents=True, exist_ok=True)
    Path("tokens").mkdir(exist_ok=True)

    engine = Engine(
        instrument="NIFTY",
        artifacts_dir=Paths.MODELS,
    )
    engine.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add main.py
git commit -m "feat: add main.py entrypoint for nifty alpha agent"
```

---

## Task 6: Fix fyers_client.py dotenv path

Currently `load_dotenv()` searches upward from cwd — fragile. Point it explicitly at `nifty_alpha_agent/.env`.

**Files:**
- Modify: `live_engine/ingestion/fyers_client.py`

- [ ] **Step 1: Write validation test**

Create `live_engine/ingestion/test_fyers_dotenv.py`:
```python
def test_dotenv_path_points_to_agent_root(tmp_path, monkeypatch):
    """The .env file load path must resolve to nifty_alpha_agent/.env."""
    import importlib
    import live_engine.ingestion.fyers_client as fc_module
    # Check the load_dotenv call receives an absolute path ending in .env
    # at the agent root (parents[2] from fyers_client.py location).
    from pathlib import Path
    expected = Path(__file__).resolve().parents[2] / ".env"
    # Verify the path calculation is correct
    fyers_client_path = Path(__file__).resolve().parent / "fyers_client.py"
    computed = fyers_client_path.parents[2] / ".env"
    assert computed == expected
    assert computed.parent.name == "nifty_alpha_agent"
```

- [ ] **Step 2: Replace the `load_dotenv()` call in fyers_client.py**

Find this line in `live_engine/ingestion/fyers_client.py`:
```python
load_dotenv()
```
Replace with:
```python
load_dotenv(Path(__file__).resolve().parents[2] / ".env")
```

Also ensure `from pathlib import Path` is present at the top of the file (it already is in the original).

- [ ] **Step 3: Commit**

```bash
git add live_engine/ingestion/fyers_client.py
git commit -m "fix: use explicit dotenv path in fyers_client — points to agent root .env"
```

---

## Task 7: Create requirements.txt

Nifty agent only — remove BTC dependencies (`growwapi`, `aiohttp` is kept for fyers async).

**Files:**
- Create: `nifty_alpha_agent/requirements.txt`

- [ ] **Step 1: Create requirements.txt**

```
# Broker APIs
# fyers-apiv3 hard-pins aiohttp==3.9.3 — install via: pip install fyers-apiv3 --no-deps
pyotp>=2.9.0

# Data
pandas>=2.1.0
numpy>=1.26.0
pyarrow>=15.0.0
fastparquet>=2023.10.0

# ML
scikit-learn>=1.4.0
xgboost>=2.0.0
joblib>=1.3.0

# Options / Greeks
mibian>=0.1.3

# Web / HTTP
httpx>=0.27.0
aiohttp>=3.11.18
requests>=2.31.0

# Database
sqlalchemy>=2.0.30
asyncpg>=0.29.0
alembic>=1.13.0

# Config
python-dotenv>=1.0.0

# Timezone
pytz>=2024.1

# Alerts
python-telegram-bot>=20.0

# SSL
certifi

# Dev
pytest>=8.0.0
```

- [ ] **Step 2: Commit**

```bash
git add requirements.txt
git commit -m "feat: add requirements.txt for nifty alpha agent"
```

---

## Task 8: Create .env.example and .gitignore

**Files:**
- Create: `nifty_alpha_agent/.env.example`
- Create: `nifty_alpha_agent/.gitignore`

- [ ] **Step 1: Create .env.example**

```
# Fyers API credentials — get from myapi.fyers.in
FYERS_CLIENT_ID=
FYERS_SECRET_KEY=
FYERS_ID=
FYERS_REDIRECT_URI=
FYERS_TOTP_SECRET=
FYERS_PIN=

# Telegram alerts
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Database (optional — leave blank to use parquet-only mode)
DATABASE_URL=

# Logging
LOG_LEVEL=INFO
```

- [ ] **Step 2: Create .gitignore**

```
# Python
.venv/
__pycache__/
*.pyc
*.pyo
*.egg-info/

# Credentials — NEVER commit these
.env
tokens/

# Runtime data
data/
logs/

# Models are committed explicitly — only ignore temp files
*.tmp
```

- [ ] **Step 3: Commit**

```bash
git add .env.example .gitignore
git commit -m "feat: add .env.example and .gitignore"
```

---

## Task 9: Create systemd service file

**Files:**
- Create: `deploy/nifty_alpha_agent.service`

- [ ] **Step 1: Create the systemd unit file**

```ini
[Unit]
Description=Nifty Alpha Trading Agent
After=network.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/nifty_alpha_agent
ExecStart=/opt/nifty_alpha_agent/.venv/bin/python main.py --shadow
Restart=on-failure
RestartSec=30
StandardOutput=append:/opt/nifty_alpha_agent/logs/nifty_alpha_agent.log
StandardError=append:/opt/nifty_alpha_agent/logs/nifty_alpha_agent.log
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Change `--shadow` to `--live` when switching to live trading on the VM.

- [ ] **Step 2: Commit**

```bash
git add deploy/nifty_alpha_agent.service
git commit -m "feat: add systemd service file for VM deployment"
```

---

## Task 10: Set up .venv and validate imports

**Files:**
- Create: `nifty_alpha_agent/.venv/`

- [ ] **Step 1: Create venv and install fyers-apiv3 without deps**

```bash
cd alpha_trading_agent/nifty_alpha_agent
python3 -m venv .venv
source .venv/bin/activate
pip install fyers-apiv3 --no-deps
pip install -r requirements.txt
```

- [ ] **Step 2: Validate import smoke test**

```bash
cd alpha_trading_agent/nifty_alpha_agent
source .venv/bin/activate
python -c "
import sys
sys.path.insert(0, 'live_engine')
from config.settings import Paths, Equity, Risk, IST, INSTRUMENT_CONFIGS, get_instrument_config
from config.instruments import FYERS_SYMBOL, LOT_SIZES
from db import get_engine
from ingestion.fyers_client import FyersClient
from model.predict import NiftyPredictor
from risk.capital_tracker import CapitalTracker
from engine import Engine
print('All imports OK')
print('ROOT:', Paths.ROOT)
print('ROOT.name:', Paths.ROOT.name)
"
```

Expected output:
```
All imports OK
ROOT: /Users/.../alpha_trading_agent/nifty_alpha_agent
ROOT.name: nifty_alpha_agent
```

- [ ] **Step 3: Run settings validation test**

```bash
cd alpha_trading_agent/nifty_alpha_agent
source .venv/bin/activate
python -c "
import sys
sys.path.insert(0, 'live_engine')
from config.settings import Paths, INSTRUMENT_CONFIGS
assert Paths.ROOT.name == 'nifty_alpha_agent', f'Got {Paths.ROOT.name}'
assert 'btc' not in Paths.DATA_DIRS, 'btc found in DATA_DIRS'
assert 'nifty' in Paths.DATA_DIRS, 'nifty missing from DATA_DIRS'
assert 'NIFTY' in INSTRUMENT_CONFIGS, 'NIFTY missing from INSTRUMENT_CONFIGS'
assert 'BANKNIFTY' not in INSTRUMENT_CONFIGS, 'BANKNIFTY should not be in this agent'
assert 'SENSEX' not in INSTRUMENT_CONFIGS, 'SENSEX should not be in this agent'
print('All settings assertions passed')
"
```

Expected output: `All settings assertions passed`

- [ ] **Step 4: If any import fails — diagnose**

If you see `ModuleNotFoundError: No module named 'core'`, sed didn't catch an import. Run:
```bash
grep -r "from core\." live_engine/ --include="*.py"
```
Fix the remaining import manually, then re-run the smoke test.

If you see `ModuleNotFoundError: No module named 'agents'`, run:
```bash
grep -r "from agents\." live_engine/ --include="*.py"
```
Fix manually, then re-run.

---

## Task 11: Create .env and run agent startup test

**Files:**
- Create: `nifty_alpha_agent/.env` (from .env.example, filled with real credentials)

- [ ] **Step 1: Copy .env.example to .env and fill in credentials**

```bash
cp .env.example .env
```

Fill in all values:
- `FYERS_CLIENT_ID` — from myapi.fyers.in (the dedicated nifty alpha agent app)
- `FYERS_SECRET_KEY`
- `FYERS_ID` — your Fyers login ID (e.g. XY12345)
- `FYERS_REDIRECT_URI` — as configured in the Fyers app
- `FYERS_TOTP_SECRET` — from authenticator app setup
- `FYERS_PIN` — your 4-digit Fyers PIN
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` — for alerts

- [ ] **Step 2: Verify dotenv loads correctly**

```bash
source .venv/bin/activate
python -c "
import sys
sys.path.insert(0, 'live_engine')
from pathlib import Path
from dotenv import load_dotenv
import os
load_dotenv(Path('live_engine/ingestion/fyers_client.py').resolve().parents[2] / '.env')
assert os.getenv('FYERS_CLIENT_ID'), 'FYERS_CLIENT_ID not loaded from .env'
print('Credentials loaded OK, FYERS_CLIENT_ID starts with:', os.getenv('FYERS_CLIENT_ID')[:4])
"
```

- [ ] **Step 3: Run startup smoke test (shadow mode)**

```bash
source .venv/bin/activate
timeout 30 python main.py --shadow --verbose 2>&1 | head -40
```

Expected: Agent initializes, logs `Engine started for NIFTY`, attempts Fyers login, then either:
- Connects successfully and starts polling — 
- Fails with auth error if credentials need refresh — this is fine, it means the code path is correct

The test fails if you see `ImportError`, `ModuleNotFoundError`, or `AttributeError`.

- [ ] **Step 4: Final commit**

```bash
git add live_engine/config/test_settings.py
git status  # confirm .env is NOT staged (should be gitignored)
git commit -m "feat: complete nifty alpha agent scaffold — imports validated, startup tested"
```

---

## Task 12: Verify git hygiene

- [ ] **Step 1: Confirm .env is gitignored**

```bash
git status
```
`.env` and `tokens/` must NOT appear in untracked files. If they do, the .gitignore isn't working — check for typos in `.gitignore`.

- [ ] **Step 2: Check repo log**

```bash
git log --oneline
```

Expected commits (in order):
```
feat: complete nifty alpha agent scaffold — imports validated, startup tested
feat: add systemd service file for VM deployment
feat: add .env.example and .gitignore
feat: add requirements.txt for nifty alpha agent
feat: add main.py entrypoint for nifty alpha agent
fix: use explicit dotenv path in fyers_client — points to agent root .env
feat: adapt settings.py for nifty-only alpha agent
feat: copy live_engine from trading_agent and fix imports
```

- [ ] **Step 3: Verify trading_agent is untouched**

```bash
cd ../../trading_agent
git status
```

Expected: `nothing to commit, working tree clean` (or your existing uncommitted changes, but no new modifications from this plan).

---

## Next Steps (Plans 2–4)

Once this plan is complete and the nifty agent is validated running in shadow mode:

- **Plan 2:** `banknifty_alpha_agent` — copy `nifty_alpha_agent/`, adapt instrument symbol, lot size, strike spacing, option chain config, and signal thresholds for BANKNIFTY
- **Plan 3:** `sensex_alpha_agent` — same as Plan 2 but for SENSEX (BSE exchange, different symbol format)
- **Plan 4:** `trading_research/` — scaffold centralized research workspace, migrate `pipelines/`, `experiments/`, `research/` from `trading_agent`
