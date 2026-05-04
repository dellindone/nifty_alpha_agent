from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from lib.journal import TradeRecord
from config.settings import IST
from config.instruments import FYERS_SYMBOL
from ingestion.fyers_client import fyers_client
from utils.market_calendar import is_trading_day

logger = logging.getLogger(__name__)

class EODHandler:
    def __init__(self, engine) -> None:
        self._e = engine

    def _handle_schedule_tasks(self, now_ist) -> None:
        def _send_exit_alert(exit_info: dict) -> None:
            try:
                record = TradeRecord(trade_id=str(exit_info["trade_id"]), instrument=str(exit_info["instrument"]), timestamp_entry=exit_info.get("entry_time", datetime.now(timezone.utc)), timestamp_exit=datetime.now(timezone.utc), direction=int(exit_info["direction"]), strike=int(exit_info["strike"]), expiry_date=exit_info["expiry_date"], option_type=str(exit_info["option_type"]), entry_premium=float(exit_info["entry_premium"]), exit_premium=float(exit_info["exit_premium"]), lot_size=int(exit_info["lot_size"]), lots=int(exit_info.get("lots", 1)), sl_price=0.0, target_price=0.0, trail_bin="", trail_tf="", confidence=float(exit_info.get("confidence", 0.0)), direction_prob=0.0, exit_reason=str(exit_info["exit_reason"]), pnl_gross=float(exit_info["pnl_gross"]), pnl_net=float(exit_info["pnl_net"]), charges=float(exit_info["charges"]), vix_at_entry=0.0, atr_at_entry=0.0, model_version="")
                self._e.reporter.send_exit_alert(record)
                self._e._last_decision = f"EXIT_{exit_info['exit_reason']}"
            except Exception as exc:
                logger.error("send_exit_alert failed: %s", exc)

        date_key = now_ist.date().isoformat()
        if is_trading_day(now_ist.date()) and now_ist.hour == 15 and now_ist.minute >= 30 and self._e._eod_closed_on != date_key:
            try:
                with self._e._tick_lock:
                    current_premiums = self._current_premiums_for_open_trades()
                    closed_exits = self._e.shadow_mode.force_close_all(current_premiums=current_premiums, reason="EOD")
                    for exit_info in closed_exits:
                        _send_exit_alert(exit_info)
                    for symbol in list(self._e._subscribed_symbols):
                        self._e._unsubscribe_if_unused(symbol)
                self._e._eod_closed_on = date_key
            except Exception as exc:
                logger.exception("eod_close_failed timestamp=%s error=%s", now_ist.isoformat(), exc)
        past_summary_time = now_ist.hour > 15 or (now_ist.hour == 15 and now_ist.minute >= 35)
        if past_summary_time and self._e._summary_sent_on != date_key:
            try:
                self._e.reporter.send_daily_summary()
                self._e._summary_sent_on = date_key
            except Exception as exc:
                logger.exception("daily_summary_failed timestamp=%s error=%s", now_ist.isoformat(), exc)

    def _maybe_send_hourly_heartbeat(self, now_ist) -> None:
        if now_ist.minute != 0:
            return
        key = now_ist.strftime("%Y-%m-%d-%H")
        if self._e._last_hourly_heartbeat_key == key:
            return
        index_price = 0.0
        try:
            quote = fyers_client.get_quotes([FYERS_SYMBOL[self._e.instrument]])
            if quote:
                index_price = float(quote[0]["v"]["lp"])
        except Exception:
            pass
        trades_today = 0
        all_trades = self._e.journal.load_all()
        if not all_trades.empty and "timestamp_entry" in all_trades.columns:
            timestamps = pd.to_datetime(all_trades["timestamp_entry"], errors="coerce", utc=True)
            trades_today = int((timestamps.dt.tz_convert(IST).dt.date == now_ist.date()).sum())
        started = self._e._started_at_ist or now_ist
        self._e.reporter.send_hourly_live_summary(instrument=self._e.instrument, open_trades=len(self._e.journal.load_open_trades()), trades_today=trades_today, capital=float(self._e.capital_tracker.current_capital), uptime_minutes=max(0, int((now_ist - started).total_seconds() // 60)), index_price=index_price)
        self._e._last_hourly_heartbeat_key = key

    def _current_premiums_for_open_trades(self) -> dict[str, float]:
        def _latest_open_trade_ltp(trade_row) -> float | None:
            instrument = str(trade_row.get("instrument", "")).upper()
            if ":" in instrument:
                return fyers_client.get_ltp(instrument)
            option_symbol = self._e._resolve_option_symbol(trade_row)
            return None if not option_symbol else fyers_client.get_ltp(option_symbol)

        def _latest_option_price_fallback(instrument: str) -> float:
            open_trades = self._e.journal.load_open_trades()
            if not open_trades.empty:
                filtered = open_trades[open_trades["instrument"].astype(str).str.upper() == instrument.upper()]
                if not filtered.empty:
                    trade = filtered.iloc[-1]
                    live = _latest_open_trade_ltp(trade)
                    if live is not None and live > 0:
                        return float(live)
                    tick_price = self._e._last_current_premiums.get(instrument.upper(), 0.0)
                    fallback = tick_price if tick_price > 0 else float(trade["entry_premium"])
                    logger.warning("eod_live_price_unavailable instrument=%s — using last_known_price=₹%.2f; PnL approximate", instrument, fallback)
                    return fallback
            return 0.0

        premiums: dict[str, float] = {}
        open_trades_df = self._e.journal.load_open_trades()
        if open_trades_df.empty:
            premiums[self._e.instrument] = _latest_option_price_fallback(self._e.instrument)
            return premiums
        for instrument_key in open_trades_df["instrument"].astype(str).str.upper().dropna().unique().tolist():
            premiums[instrument_key] = _latest_option_price_fallback(instrument_key)
        return premiums
