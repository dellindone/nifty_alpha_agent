from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from brokers.base import OrderType, Product, Segment, TransactionType
from brokers.factory import BrokerFactory
from config.settings import Trading
from db import get_engine, upsert_live_trade
from live_mode_fills import _live_row, confirm_entry_fill, confirm_exit_fill
from live_mode_restore import restore_open_trades
from live_mode_types import LiveTrade, PendingEntry
from risk.capital_tracker import CapitalTracker

logger = logging.getLogger(__name__)


class LiveModeExecutor:
    def __init__(self, journal, capital_tracker: CapitalTracker, reporter=None, health=None, dry_run: bool = False) -> None:
        self.journal = journal; self.capital_tracker = capital_tracker; self.reporter = reporter; self.health = health; self.model_version = os.getenv("MODEL_VERSION", "v1.0")
        self.broker_name = Trading.BROKER_NAME; self.account_name = Trading.ACCOUNT_NAME; self.segment = Segment.FNO
        self._dry_run = dry_run
        self._dry_fill_prices: dict[str, float] = {}
        self.broker = BrokerFactory.create(self.broker_name); self._engine = get_engine(); self._open: dict[str, LiveTrade] = {}; self._pending: dict[str, PendingEntry] = {}; restore_open_trades(self)

    def _broker_call(self, name: str, *args):
        if self._dry_run:
            if name == "place_order":
                fake_id = f"DRY-{uuid4()}"
                logger.info("[DRY-RUN] broker.%s skipped symbol=%s → order_id=%s", name, args[0] if args else "", fake_id)
                return {"order_id": fake_id}
            if name == "get_order_executed_price":
                order_id = str(args[0]) if args else ""
                price = self._dry_fill_prices.pop(order_id, None)
                logger.info("[DRY-RUN] broker.%s order_id=%s → %.2f", name, order_id, price or 0.0)
                return price
            if name == "get_order_status":
                return "TRADED"
            if name == "get_available_balance":
                return float(self.capital_tracker.get_available_capital())
            if name == "cancel_order":
                logger.info("[DRY-RUN] broker.%s skipped order_id=%s", name, args[0] if args else "")
                return {}
            logger.info("[DRY-RUN] broker.%s skipped args=%s", name, args)
            return {}
        try:
            result = getattr(self.broker, name)(*args)
            if self.health: self.health.update("broker_api", "ok", "")
            return result
        except Exception as exc:
            if self.health: self.health.update("broker_api", "critical", str(exc))
            logger.error("broker %s failed symbol=%s error=%s", name, args[0] if args else "", exc)
            raise

    def enter_trade(self, signal, option_symbol: str = ""):
        instrument = signal.instrument.upper()
        if any(t.signal.instrument.upper() == instrument for t in self._open.values()) or any(p.signal.instrument.upper() == instrument for p in self._pending.values()): return None
        trade_id = str(uuid4()); required_margin = float(signal.entry_premium) * int(signal.lot_size) * int(signal.lots)
        available_balance = self._available_balance_for_entry()
        if available_balance is not None and float(available_balance) < required_margin:
            self._send_insufficient_balance_alert(
                instrument=instrument,
                required_margin=required_margin,
                available_balance=float(available_balance),
                option_symbol=option_symbol,
            )
            return None
        if self.capital_tracker.get_available_capital() < required_margin or not self.capital_tracker.reserve_margin(trade_id, required_margin):
            self._send_insufficient_balance_alert(
                instrument=instrument,
                required_margin=required_margin,
                available_balance=float(self.capital_tracker.get_available_capital()),
                option_symbol=option_symbol,
            )
            return None
        result = self._broker_call("place_order", option_symbol, int(signal.lot_size) * int(signal.lots), TransactionType.BUY, OrderType.MARKET, self.segment, Product.NRML)
        if self._dry_run:
            self._dry_fill_prices[result["order_id"]] = float(signal.entry_premium)
        trade = LiveTrade(trade_id=trade_id, signal=signal, entry_time=datetime.now(timezone.utc), current_sl=float(signal.entry_premium) - float(signal.sl_price), highest_premium=float(signal.entry_premium), current_target=float(signal.entry_premium) + float(signal.target_price), option_symbol=str(option_symbol).upper(), broker_order_id=result.get("order_id"), lots=int(signal.lots))
        self._open[trade_id] = trade; upsert_live_trade(self._engine, _live_row(self, trade)); return trade

    def tick(self, instrument: str, current_premium: float, current_time: datetime) -> list[dict]:
        from config.settings import get_instrument_config
        closed = []
        for trade in list(self._open.values()):
            if trade.signal.instrument.upper() != instrument.upper(): continue
            if trade.trade_state == "PENDING": confirm_entry_fill(self, trade); continue
            if trade.trade_state == "SL_HIT":
                info = confirm_exit_fill(self, trade, current_time)
                if info: closed.append(info)
                continue
            premium = float(current_premium)
            if premium > trade.highest_premium: trade.highest_premium = premium
            cfg = get_instrument_config(trade.signal.instrument); act = float(trade.fill_price or trade.signal.entry_premium) + float(trade.signal.target_price) * cfg.trail_activation_rr
            if premium >= act and not trade.trail_active: trade.trail_active = True; trade.current_sl = max(trade.current_sl, act - float(trade.signal.sl_price) * cfg.trail_width_mult)
            if trade.trail_active: trade.current_sl = max(trade.current_sl, trade.highest_premium - float(trade.signal.sl_price) * cfg.trail_width_mult)
            if premium <= trade.current_sl:
                result = self._broker_call("place_order", trade.option_symbol, int(trade.signal.lot_size) * int(trade.lots), TransactionType.SELL, OrderType.MARKET, self.segment, Product.NRML)
                if self._dry_run:
                    self._dry_fill_prices[result["order_id"]] = premium
                trade.broker_exit_order_id, trade.trade_state, trade.exit_reason = result.get("order_id"), "SL_HIT", "TRAIL_SL" if trade.trail_active else "SL_HIT"
            upsert_live_trade(self._engine, _live_row(self, trade))
        return closed

    def force_close_all(self, current_premiums: dict, reason: str = "EOD") -> list[dict]:
        now, closed = datetime.now(timezone.utc), []
        for trade in list(self._open.values()):
            if trade.trade_state == "PENDING":
                filled = confirm_entry_fill(self, trade)
                if not filled and trade.trade_state == "PENDING":
                    try: self._broker_call("cancel_order", str(trade.broker_order_id))
                    except Exception: pass
                    trade.trade_state = "FAILED"; self._open.pop(trade.trade_id, None); self.capital_tracker.release_margin(trade.trade_id, 0.0); upsert_live_trade(self._engine, _live_row(self, trade))
                continue
            if trade.trade_state == "SL_HIT":
                info = confirm_exit_fill(self, trade, now)
                if info: closed.append(info)
                continue
            if trade.trade_state != "OPEN": continue
            result = self._broker_call("place_order", trade.option_symbol, int(trade.signal.lot_size) * int(trade.lots), TransactionType.SELL, OrderType.MARKET, self.segment, Product.NRML)
            if self._dry_run:
                self._dry_fill_prices[result["order_id"]] = float(current_premiums.get(trade.signal.instrument.upper(), trade.signal.entry_premium))
            trade.broker_exit_order_id, trade.exit_reason = result.get("order_id"), reason; info = confirm_exit_fill(self, trade, now)
            if info: closed.append(info)
        return closed

    def open_trades(self) -> list: return list(self._open.values())
    def set_pending(self, signal, option_symbol: str) -> PendingEntry | None:
        if not str(option_symbol).strip(): return None
        key = str(signal.instrument).upper(); now = datetime.now(timezone.utc)
        self._pending[key] = PendingEntry(signal=signal, entry_price=float(signal.entry_premium), option_symbol=str(option_symbol).upper(), created_at=now, expires_at=now + timedelta(minutes=15)); return self._pending[key]
    def check_pending_fill(self, symbol: str, ltp: float, current_time: datetime):
        for key, pending in list(self._pending.items()):
            if pending.option_symbol.upper() != str(symbol).upper(): continue
            if current_time >= pending.expires_at: self._pending.pop(key, None); return None
            if float(ltp) <= float(pending.entry_price): self._pending.pop(key, None); return self.enter_trade(pending.signal, option_symbol=str(symbol).upper())
        return None
    def get_pending_symbols(self) -> list[str]:
        now = datetime.now(timezone.utc); return [pending.option_symbol for pending in self._pending.values() if now < pending.expires_at]
    def cancel_expired_pending(self, current_time: datetime) -> list[str]:
        expired = [p.option_symbol for p in self._pending.values() if current_time >= p.expires_at]
        for key, pending in list(self._pending.items()):
            if current_time >= pending.expires_at: self._pending.pop(key, None)
        return expired
    def open_trade_display_snapshots(self) -> list[dict]:
        return [{"option_type": str(t.signal.option_type), "strike": int(t.signal.strike), "expiry_date": t.signal.expiry_date, "entry_premium": float(t.fill_price or t.signal.entry_premium), "current_sl": float(t.current_sl), "current_target": float(t.current_target), "lot_size": int(t.signal.lot_size), "lots": int(t.lots), "entry_time": t.entry_time, "confidence": float(t.signal.confidence), "option_symbol": t.option_symbol} for t in self._open.values()]

    def _available_balance_for_entry(self) -> float | None:
        balance = None
        try:
            balance = self._broker_call("get_available_balance")
        except Exception as exc:
            logger.warning("broker balance lookup failed broker=%s error=%s", self.broker_name, exc)
        if balance is None:
            balance = float(self.capital_tracker.get_available_capital())
        return None if balance is None else float(balance)

    def _send_insufficient_balance_alert(
        self,
        *,
        instrument: str,
        required_margin: float,
        available_balance: float,
        option_symbol: str = "",
    ) -> None:
        logger.warning(
            "live_entry_skipped_low_balance broker=%s instrument=%s required=%.2f available=%.2f option_symbol=%s",
            self.broker_name,
            instrument,
            required_margin,
            available_balance,
            option_symbol,
        )
        if self.reporter is None:
            return
        self.reporter.send_health_alert(
            "🚫 LIVE TRADE SKIPPED — LOW BALANCE\n"
            f"Broker: {self.broker_name}\n"
            f"Instrument: {instrument}\n"
            f"Required: ₹{required_margin:,.2f}\n"
            f"Available: ₹{available_balance:,.2f}\n"
            f"Contract: {option_symbol or '-'}\n"
            "Action: Order not placed."
        )
