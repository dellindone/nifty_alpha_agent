from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from candle_frames import fetch_live_frames
from config.settings import IST, get_instrument_config
from features.engineering import build_feature_frame

logger = logging.getLogger(__name__)


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
                frames = fetch_live_frames(self._e, now_ist); self._e.health.update("fyers_candle_api", "ok", "")
            except Exception as exc:
                self._e.health.update("fyers_candle_api", "critical", str(exc)); return
            if not frames:
                return
            try:
                feature_frame = build_feature_frame(frames, instrument=self._e.instrument)
            except Exception as exc:
                self._e.health.update("feature_pipeline", "critical", str(exc)); raise
            if feature_frame.empty:
                self._e._last_decision = "NO_FEATURE_ROW"; self._e._log_poll(now_ist, "NO_FEATURE_ROW"); self._e._print_live_display(now_ist); return
            feature_row, row = feature_frame.iloc[[-1]].copy(), feature_frame.iloc[-1]
            model_input = feature_row.reindex(columns=self._e.predictor.selected_features); nan_cols = [c for c in model_input.columns if model_input[c].isna().all()]
            self._e.health.update("feature_pipeline", "warn" if nan_cols else "ok", f"NaN in: {','.join(nan_cols)}" if nan_cols else "")
            vix = row.get("vix", 0.0); self._e.health.update("fyers_vix", "warn" if float(vix) <= 0.0 else "ok", "vix returned 0" if float(vix) <= 0.0 else ""); self._e._last_vix, self._e._last_atr = float(vix), float(row.get("atr_14", 0.0))
            close = float(row.get("close", 0.0))
            if close > 0: self._e._last_index_price = close
            try:
                prediction = self._e.predictor.predict(feature_row); self._e.health.update("model_predict", "ok", "")
            except Exception as exc:
                self._e.health.update("model_predict", "critical", str(exc)); raise
            self._e._last_pred_data = {"direction": "CE" if prediction.direction == 1 else "PE", "confidence": float(prediction.confidence), "sl_bin": str(prediction.sl_bin), "trail_bin": str(prediction.trail_bin), "trail_tf": str(prediction.trail_tf), "sl_price": 0.0, "target_price": float(prediction.phase1_target)}
            today_ist = datetime.now(IST).date(); self._e._last_daily_pnl, self._e._last_daily_count = self._daily_realized_pnl(today_ist), self._daily_trade_count_today(today_ist); date_key = str(today_ist)
            if self._e._last_daily_pnl >= get_instrument_config(self._e.instrument).daily_target and self._e._daily_target_alerted_on != date_key:
                self._e.reporter.send_daily_target_alert(self._e._last_daily_pnl); self._e._daily_target_alerted_on = date_key
            cutoff = now_ist.hour > 15 or (now_ist.hour == 15 and now_ist.minute >= 15)
            trade_signal = None if cutoff else self._e.signal_handler.process(prediction=prediction, feature_row=feature_row, instrument=self._e.instrument, daily_pnl=self._e._last_daily_pnl, daily_trade_count=self._e._last_daily_count)
            if trade_signal is None and cutoff: self._e.signal_handler.last_block_reason = "NO_NEW_TRADES_AFTER_15:15"
            if trade_signal is not None and trade_signal.blocked:
                self._e.reporter.send_signal_alert(trade_signal, blocked=True); self._e._last_decision = f"NO_SIGNAL ({trade_signal.block_reason})"; signal_label = "NONE"
            elif trade_signal is not None: signal_label = self._e._handle_trade_signal(trade_signal, prediction)
            else:
                signal_label = "NONE"; reason = self._e.signal_handler.last_block_reason or self._e._build_no_signal_decision(prediction); self._e._last_decision = f"NO_SIGNAL ({reason})"
            self._e._log_poll(now_ist, signal_label, len(self._e.journal.open_trades())); self._e._print_live_display(now_ist)
        except Exception as exc:
            logger.exception("poll_failed timestamp=%s error=%s", now_ist.isoformat(), exc)

    def _daily_realized_pnl(self, today) -> float:
        df = self._e.journal.load_all()
        if df.empty: return 0.0
        exits = df.dropna(subset=["timestamp_exit"])
        if exits.empty: return 0.0
        exit_ts = pd.to_datetime(exits["timestamp_exit"], errors="coerce", utc=True); today_closed = exits[exit_ts.dt.tz_convert(IST).dt.date == today]
        return float(pd.to_numeric(today_closed["pnl_net"], errors="coerce").fillna(0.0).sum())

    def _daily_trade_count_today(self, today) -> int:
        df = self._e.journal.load_all()
        if df.empty: return 0
        entry_ts = pd.to_datetime(df["timestamp_entry"], errors="coerce", utc=True)
        return int((entry_ts.dt.tz_convert(IST).dt.date == today).sum())
