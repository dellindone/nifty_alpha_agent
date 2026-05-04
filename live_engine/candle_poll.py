from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

import pandas as pd

from config.instruments import FYERS_SYMBOL
from config.settings import Equity, IST, get_instrument_config
from features.engineering import build_feature_frame
from ingestion.fyers_client import fyers_client

logger = logging.getLogger(__name__)

# TTL per resolution — slower timeframes change less often.
_FRAME_TTL: dict[str, timedelta] = {
    "5":  timedelta(minutes=5),
    "15": timedelta(minutes=15),
    "60": timedelta(minutes=60),
    "D":  timedelta(hours=12),
    "VIX": timedelta(minutes=10),
}

# Shared cache keyed by (symbol, resolution) — one fetch serves all agents.
_frame_cache: dict[tuple[str, str], tuple[pd.DataFrame, datetime]] = {}
_frame_cache_lock = threading.Lock()


def _get_cached_frame(symbol: str, resolution: str, fetch_fn) -> pd.DataFrame | None:
    key = (symbol, resolution)
    now = datetime.now(IST)
    ttl = _FRAME_TTL.get(resolution, timedelta(minutes=5))

    # Fast path — no lock needed if cache is fresh.
    cached = _frame_cache.get(key)
    if cached is not None and (now - cached[1]) <= ttl:
        return cached[0]

    # Slow path — serialize fetches so only one thread hits the API per stale key.
    with _frame_cache_lock:
        cached = _frame_cache.get(key)  # re-check after acquiring lock
        if cached is not None and (now - cached[1]) <= ttl:
            return cached[0]
        fetched = fetch_fn(symbol, resolution)
        if not fetched.empty:
            _frame_cache[key] = (fetched, now)
            return fetched
        return cached[0] if cached is not None else None


class CandlePoll:
    def __init__(self, engine) -> None:
        self._e = engine

    def _run_candle_poll(self, now_ist: datetime) -> None:
        try:
            with self._e._tick_lock:
                self._e._poll_count += 1
                for symbol in self._e.shadow_mode.cancel_expired_pending(now_ist.astimezone(timezone.utc)):
                    self._e._unsubscribe_if_unused(symbol)
            try:
                frames = self._fetch_live_frames(now_ist)
                self._e.health.update("fyers_candle_api", "ok", "")
            except Exception as exc:
                self._e.health.update("fyers_candle_api", "critical", str(exc))
                return
            if not frames:
                return
            try:
                feature_frame = build_feature_frame(frames, instrument=self._e.instrument)
            except Exception as exc:
                self._e.health.update("feature_pipeline", "critical", str(exc))
                raise
            if feature_frame.empty:
                self._e._last_decision = "NO_FEATURE_ROW"
                self._e._log_poll(now_ist, "NO_FEATURE_ROW")
                self._e._print_live_display(now_ist)
                return
            feature_row, row = feature_frame.iloc[[-1]].copy(), feature_frame.iloc[[-1]].copy().iloc[-1]
            model_input = feature_row.reindex(columns=self._e.predictor.selected_features)
            nan_cols = [c for c in model_input.columns if model_input[c].isna().all()]
            self._e.health.update("feature_pipeline", "warn" if nan_cols else "ok", f"NaN in: {','.join(nan_cols)}" if nan_cols else "")
            self._e._last_vix, self._e._last_atr = float(row.get("vix", 0.0)), float(row.get("atr_14", 0.0))
            vix = float(row.get("vix", 0.0))
            self._e.health.update("fyers_vix", "warn" if vix <= 0.0 else "ok", "vix returned 0" if vix <= 0.0 else "")
            close = float(row.get("close", 0.0))
            if close > 0:
                self._e._last_index_price = close
            try:
                prediction = self._e.predictor.predict(feature_row)
                self._e.health.update("model_predict", "ok", "")
            except Exception as exc:
                self._e.health.update("model_predict", "critical", str(exc))
                raise
            self._e._last_pred_data = {"direction": "CE" if prediction.direction == 1 else "PE", "confidence": float(prediction.confidence), "sl_bin": str(prediction.sl_bin), "trail_bin": str(prediction.trail_bin), "trail_tf": str(prediction.trail_tf), "sl_price": 0.0, "target_price": float(prediction.phase1_target)}
            today_ist = datetime.now(IST).date()
            self._e._last_daily_pnl, self._e._last_daily_count = self._daily_realized_pnl(today_ist), self._daily_trade_count_today(today_ist)
            date_key = str(today_ist)
            if self._e._last_daily_pnl >= get_instrument_config(self._e.instrument).daily_target and self._e._daily_target_alerted_on != date_key:
                self._e.reporter.send_daily_target_alert(self._e._last_daily_pnl)
                self._e._daily_target_alerted_on = date_key
            if now_ist.hour > 15 or (now_ist.hour == 15 and now_ist.minute >= 15):
                trade_signal = None
                self._e.signal_handler.last_block_reason = "NO_NEW_TRADES_AFTER_15:15"
            else:
                trade_signal = self._e.signal_handler.process(prediction=prediction, feature_row=feature_row, instrument=self._e.instrument, daily_pnl=self._e._last_daily_pnl, daily_trade_count=self._e._last_daily_count)
            if trade_signal is not None and trade_signal.blocked:
                self._e.reporter.send_signal_alert(trade_signal, blocked=True)
                self._e._last_decision = f"NO_SIGNAL ({trade_signal.block_reason})"
                signal_label = "NONE"
            elif trade_signal is not None:
                signal_label = self._e._handle_trade_signal(trade_signal, prediction)
            else:
                signal_label = "NONE"
                reason = self._e.signal_handler.last_block_reason or self._e._build_no_signal_decision(prediction)
                self._e._last_decision = f"NO_SIGNAL ({reason})"
            self._e._log_poll(now_ist, signal_label, len(self._e.journal.open_trades()))
            self._e._print_live_display(now_ist)
        except Exception as exc:
            logger.exception("poll_failed timestamp=%s error=%s", now_ist.isoformat(), exc)

    def _fetch_live_frames(self, now_ist: datetime) -> dict[str, pd.DataFrame]:
        sym = FYERS_SYMBOL[self._e.instrument]

        def _fetch(symbol: str, resolution: str, *, bars: int, days_back: int) -> pd.DataFrame:
            end_date = datetime.now(IST).date()
            start_date = end_date - timedelta(days=days_back)
            candles = fyers_client.get_historical(symbol=symbol, resolution=resolution, date_from=start_date.strftime("%Y-%m-%d"), date_to=end_date.strftime("%Y-%m-%d"))
            if not candles:
                return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
            df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
            return df.set_index("timestamp").sort_index().tail(bars).copy()

        frame_5m  = _get_cached_frame(sym, "5",  lambda s, r: _fetch(s, r, bars=200, days_back=30))
        frame_15m = _get_cached_frame(sym, "15", lambda s, r: _fetch(s, r, bars=200, days_back=60))
        frame_60m = _get_cached_frame(sym, "60", lambda s, r: _fetch(s, r, bars=200, days_back=99))
        frame_D   = _get_cached_frame(sym, "D",  lambda s, r: _fetch(s, r, bars=200, days_back=365))

        # Any required frame still cold after a failed fetch — skip poll gracefully.
        missing = [r for r, f in [("5m", frame_5m), ("60m", frame_60m), ("D", frame_D)] if f is None]
        if missing:
            self._e.health.update("fyers_candle_api", "critical", ",".join(missing))
            logger.warning("Frames unavailable (rate-limited) %s for %s, skipping poll", missing, self._e.instrument)
            self._e._last_decision = f"NO_SIGNAL (FRAMES_UNAVAILABLE:{','.join(missing)})"
            self._e._log_poll(now_ist, "SKIP")
            self._e._print_live_display(now_ist)
            return {}

        vix_5m = _get_cached_frame("NSE:INDIAVIX-INDEX", "VIX", lambda s, r: _fetch("NSE:INDIAVIX-INDEX", "5", bars=400, days_back=30))
        if vix_5m is None:
            self._e.health.update("fyers_vix", "warn", "unavailable")
            logger.warning("VIX unavailable (rate-limited), skipping poll for %s", self._e.instrument)
            self._e._last_decision = "NO_SIGNAL (VIX_UNAVAILABLE)"
            self._e._log_poll(now_ist, "SKIP")
            self._e._print_live_display(now_ist)
            return {}

        if "close" in vix_5m.columns:
            left = frame_5m.sort_index().reset_index().rename(columns={"index": "timestamp"})
            right = vix_5m[["close"]].rename(columns={"close": "vix"}).sort_index().reset_index().rename(columns={"index": "timestamp"})
            frame_5m = pd.merge_asof(left, right, on="timestamp", direction="backward").set_index("timestamp").sort_index()

        return {"5": frame_5m, "15": frame_15m, "60": frame_60m, "D": frame_D, "5m": frame_5m, "15m": frame_15m, "60m": frame_60m}

    def _daily_realized_pnl(self, today) -> float:
        df = self._e.journal.load_all()
        if df.empty:
            return 0.0
        exits = df.dropna(subset=["timestamp_exit"])
        if exits.empty:
            return 0.0
        exit_ts = pd.to_datetime(exits["timestamp_exit"], errors="coerce", utc=True)
        today_closed = exits[exit_ts.dt.tz_convert(IST).dt.date == today]
        return float(pd.to_numeric(today_closed["pnl_net"], errors="coerce").fillna(0.0).sum())

    def _daily_trade_count_today(self, today) -> int:
        df = self._e.journal.load_all()
        if df.empty:
            return 0
        entry_ts = pd.to_datetime(df["timestamp_entry"], errors="coerce", utc=True)
        return int((entry_ts.dt.tz_convert(IST).dt.date == today).sum())
