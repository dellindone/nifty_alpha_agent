from __future__ import annotations

from datetime import datetime

import pandas as pd

from config.settings import get_instrument_config
from lib.signal_handler import TradeSignal
from ingestion.option_chain import option_chain_service


class SignalRouter:
    def __init__(self, engine) -> None:
        self._e = engine

    def _handle_trade_signal(self, trade_signal, prediction) -> str:
        self._e._last_pred_data["sl_price"] = float(trade_signal.sl_price)
        option_symbol = self._resolve_option_symbol_from_signal(trade_signal)
        if option_symbol is None:
            self._e._last_decision = f"SIGNAL_{trade_signal.option_type}_NO_OPTION_SYMBOL"
            return trade_signal.option_type
        with self._e._tick_lock:
            before = set(self._e.executor.get_pending_symbols())
            pending = None if self._e.executor.open_trades() else self._e.executor.set_pending(trade_signal, option_symbol)
            after = set(self._e.executor.get_pending_symbols())
        for symbol in sorted(before - after):
            with self._e._tick_lock:
                self._e._unsubscribe_if_unused(symbol)
        if pending is not None:
            with self._e._tick_lock:
                self._e._ensure_subscribed([pending.option_symbol])
            self._e._last_current_premiums[self._e.instrument] = float(trade_signal.entry_premium)
            self._e._last_decision = f"PENDING_{trade_signal.option_type}_AT_{trade_signal.entry_premium:.0f}"
        else:
            self._e._last_decision = f"SIGNAL_{trade_signal.option_type}_BLOCKED"
        return trade_signal.option_type

    def _build_no_signal_decision(self, prediction) -> str:
        if self._e._last_vix > 30.0:
            return f"BLOCKED_VIX_{self._e._last_vix:.1f}"
        if float(prediction.confidence) < get_instrument_config(self._e.instrument).min_confidence:
            return f"LOW_CONF_{float(prediction.confidence):.2f}"
        return "NO_SIGNAL"

    def _resolve_option_symbol(self, trade_row: pd.Series) -> str | None:
        instrument = str(trade_row.get("instrument", self._e.instrument)).upper()
        raw_strike = trade_row.get("strike")
        strike = int(float(raw_strike)) if pd.notna(raw_strike) and raw_strike not in (None, "") else 0
        option_type = str(trade_row.get("option_type", "")).upper()
        expiry_ts = pd.to_datetime(trade_row.get("expiry_date"), errors="coerce")
        if pd.isna(expiry_ts) or strike <= 0 or option_type not in {"CE", "PE"}:
            return None
        csv_df = option_chain_service._fetch_csv(instrument)
        if csv_df is None or csv_df.empty:
            self._e.health.update("fyers_option_chain", "warn", "option chain CSV empty")
            return None
        try:
            strike_mask = pd.to_numeric(csv_df[15], errors="coerce") == float(strike)
            type_mask = csv_df[9].astype(str).str.upper().str.endswith(option_type)
            def _symbol_expiry_matches(sym: str) -> bool:
                try:
                    core, rest = sym.split(":")[-1], sym.split(":")[-1][len(instrument):]
                    if len(rest) < 5:
                        return False
                    if rest[2:5].isalpha():
                        parsed = datetime.strptime(rest[:5], "%y%b")
                        return parsed.year == expiry_ts.year and parsed.month == expiry_ts.month
                    month_map, m_char = {"O": 10, "N": 11, "D": 12}, rest[2]
                    from datetime import date as _date
                    return _date(2000 + int(rest[:2]), month_map.get(m_char, int(m_char)), int(rest[3:5])) == expiry_ts.date()
                except Exception:
                    return False
            matched = csv_df[strike_mask & type_mask & csv_df[9].astype(str).apply(_symbol_expiry_matches)]
        except Exception:
            return None
        if matched.empty:
            self._e.health.update("fyers_option_chain", "warn", "no matching symbol")
            return None
        symbol = str(matched.iloc[0][9])
        self._e.health.update("fyers_option_chain", "ok", "")
        return symbol if symbol else None

    def _resolve_option_symbol_from_signal(self, signal: TradeSignal) -> str | None:
        instrument, strike, option_type, expiry_date = str(signal.instrument).upper(), int(signal.strike), str(signal.option_type).upper(), signal.expiry_date
        if strike <= 0 or option_type not in {"CE", "PE"}:
            return None
        csv_df = option_chain_service._fetch_csv(instrument)
        if csv_df is None or csv_df.empty:
            self._e.health.update("fyers_option_chain", "warn", "option chain CSV empty")
            return None
        try:
            strike_mask = pd.to_numeric(csv_df[15], errors="coerce") == float(strike)
            type_mask = csv_df[9].astype(str).str.upper().str.endswith(option_type)
            def _symbol_expiry_matches(sym: str) -> bool:
                try:
                    core, rest = sym.split(":")[-1], sym.split(":")[-1][len(instrument):]
                    if len(rest) < 5:
                        return False
                    if rest[2:5].isalpha():
                        parsed = datetime.strptime(rest[:5], "%y%b")
                        return parsed.year == expiry_date.year and parsed.month == expiry_date.month
                    month_map, m_char = {"O": 10, "N": 11, "D": 12}, rest[2]
                    from datetime import date as _date
                    return _date(2000 + int(rest[:2]), month_map.get(m_char, int(m_char)), int(rest[3:5])) == expiry_date
                except Exception:
                    return False
            matched = csv_df[strike_mask & type_mask & csv_df[9].astype(str).apply(_symbol_expiry_matches)]
        except Exception:
            return None
        if matched.empty:
            self._e.health.update("fyers_option_chain", "warn", "no matching symbol")
            return None
        symbol = str(matched.iloc[0][9])
        self._e.health.update("fyers_option_chain", "ok", "")
        return symbol if symbol else None
