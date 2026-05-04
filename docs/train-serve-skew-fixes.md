# Train-Serve Skew — Root Cause Analysis & Fixes

**Date:** 2026-05-05  
**Branch:** V1  
**Symptom:** Model predicted CE (bullish) trades on May 4, 2026 when NIFTY was falling after 9:30 AM IST. All 3 trades hit SL. Shadow mode found 0 valid trades all day.

---

## Root Causes Found

### 1. Partial (unclosed) bar used for prediction
**File:** `live_engine/candle_poll.py:80`

In simulation, every bar is a closed complete OHLCV bar. In live mode, Fyers returns the current forming bar as the last entry when `range_to = today`. Using `iloc[-1]` fed the model a partial bar with mid-candle values for `high`, `low`, `close`, `body_size`, `upper_wick`, `lower_wick` — all selected features. The model was never trained on partial bars.

**Fix:** Changed to `iloc[-2]` (last fully closed bar).

---

### 2. EMA-200 daily warmup bias
**File:** `live_engine/candle_poll.py` (fetch params)

With only 200 daily bars fetched, `ema_200_D` was SMA-initialized (pandas default). SMA of 200 days ≈ historical average ≈ ~23,500. With NIFTY trading above that at 09:50, `ema_200_D` looked bullish. A properly warmed EMA-200 needs 600+ daily bars to converge.

`ema_stack_bull_D` (used in `bull_context_score`) checks `ema_20 > ema_50 > ema_200`. With low `ema_200_D`, this condition was trivially True → `bull_context_score` inflated, `bear_context_score` deflated. Both are selected model features.

**Fix:** Increased daily frame to `bars=600, days_back=900`.

---

### 3. No entry filter before 09:45 IST
**File:** `live_engine/lib/signal_handler.py`

Trades at 09:50, 10:05, 10:10 were entered when:
- Opening range features (`dist_to_or_high_atr`, `opening_range_high`) had only 2–7 bars of history
- `pcr_premium` rolling-20 had fewer than 10 data points
- Session momentum features were noisy

**Fix:** Added `min_session_bar = 6` to `InstrumentConfig` (default). Bar 6 = 09:45 close. Signals blocked before that bar with reason `TOO_EARLY`.

---

### 4. `days_to_expiry` hardcoded to 7
**File:** `live_engine/features/engineering.py`

`build_premium_history` always used `days_to_expiry=7` to compute `ce_premium` / `pe_premium`. On expiry week (DTE=1–2), ATM option premiums are 60–80% lower than at DTE=7. The model was trained with varying DTE, so live features were systematically wrong every expiry week.

**Fix:** `actual_dte = market_calendar.days_to_next_expiry(instrument, last_date)` computed at feature-build time.

---

### 5. Duplicate polls — two processes running simultaneously
**File:** `main.py`

systemd `Restart=always` can race-start a new instance before the previous crashed process fully exits. Both run in parallel → every 5m poll fires twice, every Telegram alert sends twice, every SL check runs twice (risk of duplicate orders in live mode).

**Fix:** Added `fcntl.flock` exclusive lock on `/tmp/nifty_alpha_agent.lock` at startup. Second instance exits immediately with a clear message.

---

## Remaining Issues (Research Pipeline)

### 6. Class imbalance — CE bias in training data
The model was trained on 2022-01-03 → 2026-04-30, a 4-year bull market. `CE_TP_FIRST` labels significantly outnumber `PE_TP_FIRST`. When features are ambiguous the model defaults to CE.

**Fix needed in research pipeline:**
- Add `class_weight="balanced"` to the direction / trade_class classifier
- Or use `scale_pos_weight = n_ce / n_pe` for XGBoost
- Or upsample PE examples with SMOTE during training

See: `trading_research/nifty/pipelines/` for the training pipeline.

---

## Summary of Code Changes

| File | Change | Impact |
|---|---|---|
| `candle_poll.py` | `iloc[-2]` instead of `iloc[-1]` | Eliminates partial bar skew |
| `candle_poll.py` | Daily: `bars=600, days_back=900` | Fixes EMA-200 warmup |
| `main.py` | PID lock via `fcntl.flock` | Prevents duplicate processes |
| `config/settings.py` | `min_session_bar=6` on `InstrumentConfig` | Blocks noisy early-morning signals |
| `lib/signal_handler.py` | Session bar check before confidence filter | Blocks trades before 09:45 IST |
| `features/engineering.py` | Actual DTE from market calendar | Fixes option premium on expiry week |

---

## How to Verify After Retraining

1. Run simulation on May 2026 OOS data
2. Check that no CE trades appear in first 6 bars (09:15–09:45) of any session
3. Check `ema_200_D` values match between research pipeline and live feature frame on the same date
4. Check `ce_premium` / `pe_premium` on expiry Thursday match actual ATM premiums
5. Compare `direction_accuracy` on PE days vs CE days — should be balanced after retrain
