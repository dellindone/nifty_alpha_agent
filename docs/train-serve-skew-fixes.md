# Train-Serve Skew Fixes (May 4, 2026 Postmortem)

This document records train-serve skew root causes found on May 4, 2026, and the fixes applied to restore parity between model training assumptions and live inference behavior.

## Issue 1 — Closed Bar Timing (`candle_poll.py`)
**Problem**: Live inference used `iloc[-1]`, which points to the currently forming bar. Training data was built on closed bars only.

**Root cause**: Feature extraction during live polling consumed partially formed OHLCV values, creating distribution shift versus offline training frames.

**Fix applied**: Switched live feature row selection from `iloc[-1]` to `iloc[-2]` so inference always runs on the latest fully closed 5-minute bar.

**Impact on model/live parity**: Signal-time features now align with training-time feature construction, removing open-bar drift.

## Issue 2 — Days-to-Expiry Calculation (`features/engineering.py`)
**Problem**: DTE was static/incorrect in live feature computation.

**Root cause**: DTE did not consistently use bar timestamp + market calendar logic for nearest weekly expiry.

**Fix applied**: DTE now calls `market_calendar.days_to_next_expiry()` using each bar’s actual timestamp.

**Impact on model/live parity**: Option-pricing-derived features (synthetic premium, moneyness context) now match training labels and expected regime.

## Issue 3 — Minimum Session Bar Gate (`config/settings.py`, `lib/signal_handler.py`)
**Problem**: Signals were generated in the 9:15–9:20 AM window where opening noise is high.

**Root cause**: No live gate to suppress early-session bars that were weakly represented/unstable for training behavior.

**Fix applied**: Added `min_session_bar` (default `6`), allowing entries only from the 6th 5-minute bar onward (9:45 AM IST).

**Impact on model/live parity**: Reduces out-of-distribution early-session decisions and improves stability of first valid signal window.

## Issue 4 — CE vs PE Direction on Falling Days
**Problem**: On May 4, 2026 (gap-down, persistent sell-off), model produced CE-biased signals.

**Root cause**: Regime/trend context used stale D-timeframe state (yesterday-biased daily bar) instead of current-session-aware daily context.

**Fix applied**: Updated D-timeframe regime input so intraday regime features reflect the current session open state, not stale prior close state.

**Impact on model/live parity**: Trend/regime features now represent same directional context intended during training and reduce bullish misclassification on bearish days.

## Issue 5 — Strike Pricing Alignment (2 ITM Selection)
**Problem**: Live selection was ATM while model-label logic assumed 2-ITM contracts.

**Root cause**: Strike selection in live path diverged from training/backtest label-generation assumptions.

**Fix applied**: Strike selector now enforces 2-ITM selection: CE = 2 strikes below spot, PE = 2 strikes above spot.

**Impact on model/live parity**: Entry premium scale, stop-loss distance, and RR dynamics now match simulation/training assumptions.

## Checklist Before Next Retrain
- Verify closed-bar consistency end-to-end (`iloc[-2]` live/replay/backtest where applicable).
- Verify DTE uses `days_to_next_expiry()` with bar timestamp (no constants).
- Verify session-bar gating is consistent between training label generation and live execution.
- Verify strike selection logic (2-ITM) is identical across backtester, replay, and live engine.
- Verify label class balance and drift for `sl_bin` and `trade_class` before finalizing artifacts.
