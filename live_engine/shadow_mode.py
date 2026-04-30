"""Shadow trade execution simulator and open-position manager."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pandas as pd

from config.settings import get_instrument_config
from config.instruments import LOT_SIZES
from risk.capital_tracker import CapitalTracker
from utils.charge_calculator import calculate_charges
from lib.journal import Journal, TradeRecord
from lib.signal_handler import TradeSignal

logger = logging.getLogger(__name__)


@dataclass
class ShadowTrade:
    trade_id: str
    signal: TradeSignal
    entry_time: datetime
    current_sl: float
    highest_premium: float
    current_target: float
    trail_active: bool = False
    lots: int = 1
    option_symbol: str = ""


@dataclass
class PendingEntry:
    signal: TradeSignal
    entry_price: float
    option_symbol: str
    created_at: datetime
    expires_at: datetime


class ShadowMode:
    def __init__(self, journal: Journal, capital_tracker: CapitalTracker) -> None:
        self.journal = journal
        self.capital_tracker = capital_tracker
        self.model_version = os.getenv("MODEL_VERSION", "v1.0")
        self._open: dict[str, ShadowTrade] = {}
        self._pending: dict[str, PendingEntry] = {}
        self._last_trail_update: dict[str, datetime] = {}
        self._restore_open_trades()

    def _restore_open_trades(self) -> None:
        """Rebuild in-memory state from parquet on startup after a crash/restart."""
        try:
            open_df = self.journal.load_open_trades()
        except Exception as exc:
            logger.warning("Could not load open trades for restore: %s", exc)
            return

        if open_df.empty:
            return

        restored = 0
        for _, row in open_df.iterrows():
            try:
                trade_id = str(row["trade_id"])
                instrument = str(row["instrument"]).upper()
                lot_size = int(float(row.get("lot_size") or LOT_SIZES.get(instrument, 65)))
                entry_premium = float(row["entry_premium"])

                expiry_raw = pd.to_datetime(row["expiry_date"], errors="coerce")
                expiry_date: date = expiry_raw.date() if not pd.isna(expiry_raw) else datetime.now(timezone.utc).date()

                signal = TradeSignal(
                    instrument=instrument,
                    direction=int(row.get("direction", 1)),
                    option_type=str(row.get("option_type", "CE")).upper(),
                    strike=int(float(row.get("strike", 0))),
                    expiry_date=expiry_date,
                    entry_premium=entry_premium,
                    sl_price=float(row.get("sl_price", 0.0)),
                    target_price=float(row.get("target_price", 0.0)),
                    trail_bin=str(row.get("trail_bin", "MEDIUM")),
                    trail_tf=str(row.get("trail_tf", "15m")),
                    confidence=float(row.get("confidence", 0.5)),
                    direction_prob=float(row.get("direction_prob", 0.5)),
                    vix=float(row.get("vix_at_entry", 15.0)),
                    atr=float(row.get("atr_at_entry", 0.0)),
                    lot_size=lot_size,
                    lots=int(float(row.get("lots", 1) or 1)),
                )

                entry_ts = pd.to_datetime(row["timestamp_entry"], errors="coerce")
                entry_time = entry_ts.to_pydatetime() if not pd.isna(entry_ts) else datetime.now(timezone.utc)
                sl_price = float(row.get("sl_price", 0.0))
                target_price = float(row.get("target_price", 0.0))
                persisted_sl = row.get("current_sl")
                persisted_peak = row.get("highest_premium")
                current_sl = float(persisted_sl) if pd.notna(persisted_sl) else (entry_premium - sl_price)
                highest_premium = float(persisted_peak) if pd.notna(persisted_peak) else entry_premium

                trade = ShadowTrade(
                    trade_id=trade_id,
                    signal=signal,
                    entry_time=entry_time,
                    current_sl=current_sl,
                    highest_premium=highest_premium,
                    current_target=entry_premium + target_price,
                    trail_active=bool(row.get("trail_active", False)),
                    lots=int(float(row.get("lots", 1) or 1)),
                )
                self._open[trade_id] = trade
                self._last_trail_update[trade_id] = datetime.now(timezone.utc)

                # Re-reserve margin so capital accounting stays correct
                margin = entry_premium * lot_size * int(getattr(trade, "lots", 1))
                self.capital_tracker._reserved_margin.setdefault(trade_id, margin)

                restored += 1
            except Exception as exc:
                logger.warning("Failed to restore trade %s: %s", row.get("trade_id"), exc)

        if restored:
            logger.info("restore_open_trades count=%d", restored)

    def enter_trade(self, signal: TradeSignal, option_symbol: str = "") -> ShadowTrade | None:
        instrument = signal.instrument.upper()
        if any(trade.signal.instrument.upper() == instrument for trade in self._open.values()):
            return None

        required_margin = float(signal.entry_premium) * int(signal.lot_size) * int(signal.lots)
        if self.capital_tracker.get_available_capital() < required_margin:
            return None

        trade_id = str(uuid4())
        if not self.capital_tracker.reserve_margin(trade_id, required_margin):
            return None

        now = datetime.now(timezone.utc)
        trade = ShadowTrade(
            trade_id=trade_id,
            signal=signal,
            entry_time=now,
            current_sl=float(signal.entry_premium) - float(signal.sl_price),
            highest_premium=float(signal.entry_premium),
            current_target=float(signal.entry_premium) + float(signal.target_price),
            lots=int(signal.lots),
            option_symbol=str(option_symbol).upper(),
        )
        self._open[trade_id] = trade
        self._last_trail_update[trade_id] = now

        record = TradeRecord(
            trade_id=trade_id,
            instrument=instrument,
            timestamp_entry=now,
            timestamp_exit=None,
            direction=int(signal.direction),
            strike=int(signal.strike),
            expiry_date=signal.expiry_date,
            option_type=str(signal.option_type),
            entry_premium=float(signal.entry_premium),
            exit_premium=None,
            lot_size=int(signal.lot_size),
            lots=int(signal.lots),
            sl_price=float(signal.sl_price),
            target_price=float(signal.target_price),
            trail_bin=str(signal.trail_bin),
            trail_tf=str(signal.trail_tf),
            confidence=float(signal.confidence),
            direction_prob=float(signal.direction_prob),
            exit_reason=None,
            pnl_gross=None,
            pnl_net=None,
            charges=None,
            vix_at_entry=float(signal.vix),
            atr_at_entry=float(signal.atr),
            model_version=self.model_version,
        )
        self.journal.log_entry(record)
        self.journal.update_trade_state(
            trade_id,
            current_sl=trade.current_sl,
            highest_premium=trade.highest_premium,
            lots=trade.lots,
        )
        return trade

    def tick(self, instrument: str, current_premium: float, current_time: datetime) -> list[dict]:
        instrument_key = instrument.upper()
        closed: list[dict] = []

        for trade_id, trade in list(self._open.items()):
            if trade.signal.instrument.upper() != instrument_key:
                continue

            premium = float(current_premium)
            if premium <= trade.current_sl:
                reason = "TRAIL_SL" if trade.trail_active else "SL_HIT"
                info = self._close_trade(trade_id, premium, reason, current_time)
                if info:
                    closed.append(info)
                continue
            cfg = get_instrument_config(trade.signal.instrument)
            act_price = (
                float(trade.signal.entry_premium)
                + float(trade.signal.target_price) * cfg.trail_activation_rr
            )
            if premium >= act_price and not trade.trail_active:
                trade.trail_active = True
                sl_distance = float(trade.signal.sl_price)
                floor_sl = act_price - sl_distance * cfg.trail_width_mult
                trade.current_sl = max(trade.current_sl, floor_sl)
                self.journal.update_trade_state(
                    trade_id,
                    current_sl=trade.current_sl,
                    highest_premium=trade.highest_premium,
                    trail_active=True,
                    lots=trade.lots,
                )

            self._update_trailing_stop(trade_id, premium, current_time)

        return closed

    def force_close_all(self, current_premiums: dict[str, float], reason: str = "EOD") -> list[dict]:
        now = datetime.now(timezone.utc)
        closed: list[dict] = []
        for trade_id, trade in list(self._open.items()):
            instrument = trade.signal.instrument.upper()
            premium = float(current_premiums.get(instrument, trade.signal.entry_premium))
            info = self._close_trade(trade_id, premium, reason, now)
            if info:
                closed.append(info)
        return closed

    def open_trades(self) -> list[ShadowTrade]:
        return list(self._open.values())

    def set_pending(self, signal: TradeSignal, option_symbol: str) -> PendingEntry | None:
        option_symbol_key = str(option_symbol).upper()
        if not option_symbol_key:
            return None

        now = datetime.now(timezone.utc)
        pending = PendingEntry(
            signal=signal,
            entry_price=float(signal.entry_premium),
            option_symbol=option_symbol_key,
            created_at=now,
            expires_at=now + timedelta(minutes=15),
        )
        self._pending[str(signal.instrument).upper()] = pending
        return pending

    def check_pending_fill(self, symbol: str, ltp: float, current_time: datetime) -> ShadowTrade | None:
        symbol_key = str(symbol).upper()
        for instrument_key, pending in list(self._pending.items()):
            if pending.option_symbol.upper() != symbol_key:
                continue
            if current_time >= pending.expires_at:
                self._pending.pop(instrument_key, None)
                return None
            if float(ltp) <= float(pending.entry_price):
                self._pending.pop(instrument_key, None)
                return self.enter_trade(pending.signal, option_symbol=symbol_key)
            return None
        return None

    def get_pending_symbols(self) -> list[str]:
        now = datetime.now(timezone.utc)
        return [
            pending.option_symbol
            for pending in self._pending.values()
            if now < pending.expires_at
        ]

    def cancel_expired_pending(self, current_time: datetime) -> list[str]:
        expired_symbols: list[str] = []
        for instrument_key, pending in list(self._pending.items()):
            if current_time >= pending.expires_at:
                expired_symbols.append(pending.option_symbol)
                self._pending.pop(instrument_key, None)
        return expired_symbols

    def open_trade_display_snapshots(self) -> list[dict]:
        return [
            {
                "option_type": str(t.signal.option_type),
                "strike": int(t.signal.strike),
                "expiry_date": t.signal.expiry_date,
                "entry_premium": float(t.signal.entry_premium),
                "current_sl": float(t.current_sl),
                "current_target": float(t.current_target),
                "lot_size": int(t.signal.lot_size),
                "lots": int(getattr(t, "lots", 1)),
                "entry_time": t.entry_time,
                "confidence": float(t.signal.confidence),
                "option_symbol": t.option_symbol,
            }
            for t in self._open.values()
        ]

    def _update_trailing_stop(self, trade_id: str, current_premium: float, current_time: datetime) -> None:
        trade = self._open.get(trade_id)
        if trade is None:
            return
        if float(current_premium) > trade.highest_premium:
            trade.highest_premium = float(current_premium)
            if trade.trail_active:
                sl_distance = float(trade.signal.sl_price)
                cfg = get_instrument_config(trade.signal.instrument)
                new_sl = trade.highest_premium - sl_distance * cfg.trail_width_mult
                if new_sl > trade.current_sl:
                    trade.current_sl = new_sl
                    self.journal.update_trade_state(
                        trade_id,
                        current_sl=trade.current_sl,
                        highest_premium=trade.highest_premium,
                        lots=trade.lots,
                    )

    def _close_trade(self, trade_id: str, exit_premium: float, reason: str, timestamp_exit: datetime) -> dict | None:
        trade = self._open.pop(trade_id, None)
        self._last_trail_update.pop(trade_id, None)
        if trade is None:
            return None

        lot_size = int(trade.signal.lot_size)
        exit_premium_f = float(exit_premium)
        lots = int(getattr(trade, "lots", 1))
        pnl_gross = (exit_premium_f - float(trade.signal.entry_premium)) * lot_size * lots
        charges = calculate_charges(
            premium=exit_premium_f,
            lot_size=lot_size,
            lots=lots,
            instrument=trade.signal.instrument.upper(),
            side="SELL",
        )["total"]
        pnl_net = pnl_gross - float(charges)

        try:
            self.journal.log_exit(
                trade_id=trade_id,
                exit_premium=exit_premium_f,
                exit_reason=str(reason),
                timestamp_exit=timestamp_exit,
                pnl_gross=pnl_gross,
                pnl_net=pnl_net,
                charges=charges,
            )
        except Exception as exc:
            logger.error("log_exit failed trade_id=%s error=%s", trade_id, exc)
        try:
            self.capital_tracker.release_margin(trade_id, pnl_net)
        except Exception as exc:
            logger.error("release_margin failed trade_id=%s error=%s", trade_id, exc)

        display_reason = "TARGET_HIT" if str(reason) in {"TARGET_HIT", "TRAIL_SL"} else str(reason)
        return {
            "trade_id": trade_id,
            "instrument": trade.signal.instrument.upper(),
            "entry_time": trade.entry_time,
            "direction": trade.signal.direction,
            "option_type": trade.signal.option_type,
            "strike": trade.signal.strike,
            "expiry_date": trade.signal.expiry_date,
            "entry_premium": float(trade.signal.entry_premium),
            "exit_premium": exit_premium_f,
            "exit_reason": display_reason,
            "lot_size": lot_size,
            "lots": lots,
            "pnl_gross": pnl_gross,
            "pnl_net": pnl_net,
            "charges": float(charges),
            "confidence": float(trade.signal.confidence),
        }


# Backward compatibility with prior integration naming.
ShadowModeExecutor = ShadowMode
