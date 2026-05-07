from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

from lib.journal import TradeRecord
from config.instruments import FYERS_SYMBOL
from config.settings import IST

logger = logging.getLogger(__name__)


class TickHandler:
    def __init__(self, engine) -> None:
        self._e = engine

    def _on_tick(self, symbol: str, ltp: float) -> None:
        def _send_exit_alert(exit_info: dict) -> None:
            try:
                record = TradeRecord(trade_id=str(exit_info["trade_id"]), instrument=str(exit_info["instrument"]), timestamp_entry=exit_info.get("entry_time", datetime.now(timezone.utc)), timestamp_exit=datetime.now(timezone.utc), direction=int(exit_info["direction"]), strike=int(exit_info["strike"]), expiry_date=exit_info["expiry_date"], option_type=str(exit_info["option_type"]), entry_premium=float(exit_info["entry_premium"]), exit_premium=float(exit_info["exit_premium"]), lot_size=int(exit_info["lot_size"]), lots=int(exit_info.get("lots", 1)), sl_price=0.0, target_price=0.0, trail_bin="", trail_tf="", confidence=float(exit_info.get("confidence", 0.0)), direction_prob=0.0, exit_reason=str(exit_info["exit_reason"]), pnl_gross=float(exit_info["pnl_gross"]), pnl_net=float(exit_info["pnl_net"]), charges=float(exit_info["charges"]), vix_at_entry=0.0, atr_at_entry=0.0, model_version="")
                self._e.reporter.send_exit_alert(record)
                self._e._last_decision = f"EXIT_{exit_info['exit_reason']}"
            except Exception as exc:
                logger.error("send_exit_alert failed: %s", exc)

        with self._e._tick_lock:
            now_utc = datetime.now(timezone.utc)
            symbol_key = str(symbol).upper()
            price = float(ltp)
            if math.isnan(price) or price <= 0:
                return
            self._e._last_tick_at = now_utc
            self._e.health.update("fyers_websocket", "ok", "")
            if symbol_key == FYERS_SYMBOL[self._e.instrument].upper():
                self._e._last_index_price = price
                self._e._print_live_display(datetime.now(IST))
                return
            trade = self._e.executor.check_pending_fill(symbol_key, price, now_utc)
            if trade is not None:
                self._e._unsubscribe_if_unused(symbol_key)
                self._e._ensure_subscribed([symbol_key])
                self._e.reporter.send_signal_alert(trade.signal)
                self._e._last_decision = f"ENTERED_{trade.signal.option_type}_AT_{price:.0f}"
            closed_exits = self._e.executor.tick(instrument=self._e.instrument, current_premium=price, current_time=now_utc)
            self._e._last_current_premiums[symbol_key] = price
            self._e._last_current_premiums[self._e.instrument] = price
            for exit_info in closed_exits:
                _send_exit_alert(exit_info)
            self._e._unsubscribe_if_unused(symbol_key)
            self._e._print_live_display(datetime.now(IST))

    def _check_websocket_staleness(self, now_ist: datetime) -> None:
        if not (now_ist.weekday() < 5 and (now_ist.hour, now_ist.minute) >= (9, 15) and (now_ist.hour, now_ist.minute) <= (15, 30)):
            return
        elapsed = int((datetime.now(timezone.utc) - self._e._last_tick_at).total_seconds())
        if elapsed > 120:
            self._e.health.update("fyers_websocket", "critical", f"no ticks for {elapsed}s")

    def _ensure_subscribed(self, symbols: list[str]) -> None:
        wanted = [str(symbol).upper() for symbol in symbols if str(symbol).strip()]
        to_add = [symbol for symbol in wanted if symbol not in self._e._subscribed_symbols]
        if not to_add:
            return
        self._e._tick_stream.subscribe(to_add)
        self._e._subscribed_symbols.update(to_add)

    def _unsubscribe_if_unused(self, symbol: str) -> None:
        symbol_key = str(symbol).upper()
        if symbol_key == FYERS_SYMBOL[self._e.instrument].upper():
            return
        pending_symbols = {str(s).upper() for s in self._e.executor.get_pending_symbols()}
        open_symbols = set(self._e._get_open_trade_symbols())
        if symbol_key in pending_symbols or symbol_key in open_symbols or symbol_key not in self._e._subscribed_symbols:
            return
        self._e._tick_stream.unsubscribe([symbol_key])
        self._e._subscribed_symbols.discard(symbol_key)
        self._e._last_current_premiums.pop(symbol_key, None)

    def _get_open_trade_symbols(self) -> list[str]:
        symbols: set[str] = set()
        open_trades_df = self._e.journal.load_open_trades()
        if open_trades_df.empty:
            return []
        for _, row in open_trades_df.iterrows():
            instrument = str(row.get("instrument", "")).upper()
            if ":" in instrument:
                symbols.add(instrument)
                continue
            option_symbol = self._e._resolve_option_symbol(row)
            if option_symbol:
                symbols.add(option_symbol.upper())
        return sorted(symbols)
