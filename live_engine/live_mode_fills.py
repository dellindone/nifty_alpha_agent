from datetime import datetime, timezone
import logging

from db import upsert_live_trade
from lib.journal import TradeRecord
from utils.charge_calculator import calculate_charges

logger = logging.getLogger(__name__)
_TERMINAL_STATUSES = {"REJECTED", "FAILED", "CANCELLED"}


def _live_row(executor, trade) -> dict:
    return {"trade_id": trade.trade_id, "account_name": executor.account_name, "broker_name": executor.broker_name, "broker_order_id": trade.broker_order_id, "broker_exit_order_id": trade.broker_exit_order_id, "trade_state": trade.trade_state, "fill_price": trade.fill_price, "exit_fill_price": trade.exit_fill_price, "instrument": trade.signal.instrument.upper(), "direction": int(trade.signal.direction), "option_type": str(trade.signal.option_type), "strike": int(trade.signal.strike), "expiry_date": trade.signal.expiry_date, "entry_premium": float(trade.signal.entry_premium), "exit_premium": trade.exit_fill_price, "lot_size": int(trade.signal.lot_size), "lots": int(trade.lots), "sl_price": float(trade.signal.sl_price), "current_sl": float(trade.current_sl), "target_price": float(trade.signal.target_price), "highest_premium": float(trade.highest_premium), "trail_active": bool(trade.trail_active), "trail_bin": str(trade.signal.trail_bin), "trail_tf": str(trade.signal.trail_tf), "vix_at_entry": float(trade.signal.vix), "atr_at_entry": float(trade.signal.atr), "confidence": float(trade.signal.confidence), "direction_prob": float(trade.signal.direction_prob), "model_version": executor.model_version, "exit_reason": trade.exit_reason, "pnl_gross": None, "pnl_net": None, "charges": None, "override": False, "timestamp_entry": trade.entry_time, "timestamp_exit": None, "option_symbol": str(trade.option_symbol).upper()}


def confirm_entry_fill(executor, trade):
    fill = executor._broker_call("get_order_executed_price", str(trade.broker_order_id), executor.segment)
    status = executor._broker_call("get_order_status", str(trade.broker_order_id), executor.segment)
    if fill is None:
        if status in _TERMINAL_STATUSES:
            trade.trade_state = "FAILED"
            upsert_live_trade(executor._engine, _live_row(executor, trade))
            executor._open.pop(trade.trade_id, None)
            executor.capital_tracker.release_margin(trade.trade_id, 0.0)
            return False
        upsert_live_trade(executor._engine, _live_row(executor, trade))
        return False
    trade.fill_price = float(fill)
    trade.trade_state = "OPEN"
    trade.current_sl = trade.fill_price - float(trade.signal.sl_price)
    trade.current_target = trade.fill_price + float(trade.signal.target_price)
    record = TradeRecord(trade_id=trade.trade_id, instrument=trade.signal.instrument.upper(), timestamp_entry=trade.entry_time, timestamp_exit=None, direction=int(trade.signal.direction), strike=int(trade.signal.strike), expiry_date=trade.signal.expiry_date, option_type=str(trade.signal.option_type), entry_premium=trade.fill_price, exit_premium=None, lot_size=int(trade.signal.lot_size), lots=int(trade.lots), sl_price=float(trade.signal.sl_price), target_price=float(trade.signal.target_price), trail_bin=str(trade.signal.trail_bin), trail_tf=str(trade.signal.trail_tf), confidence=float(trade.signal.confidence), direction_prob=float(trade.signal.direction_prob), exit_reason=None, pnl_gross=None, pnl_net=None, charges=None, vix_at_entry=float(trade.signal.vix), atr_at_entry=float(trade.signal.atr), model_version=executor.model_version, account_name=executor.account_name, broker_name=executor.broker_name, option_symbol=str(trade.option_symbol).upper())
    executor.journal.log_entry(record)
    executor.journal.update_trade_state(trade.trade_id, current_sl=trade.current_sl, highest_premium=trade.highest_premium, lots=trade.lots)
    upsert_live_trade(executor._engine, _live_row(executor, trade))
    logger.info("fill confirmed trade_id=%s fill_price=%.2f state=%s", trade.trade_id, trade.fill_price, trade.trade_state)
    return True


def confirm_exit_fill(executor, trade, now: datetime):
    fill = executor._broker_call("get_order_executed_price", str(trade.broker_exit_order_id), executor.segment)
    status = executor._broker_call("get_order_status", str(trade.broker_exit_order_id), executor.segment)
    if fill is None:
        if status in _TERMINAL_STATUSES:
            trade.trade_state = "FAILED"
            upsert_live_trade(executor._engine, _live_row(executor, trade))
            return None
        upsert_live_trade(executor._engine, _live_row(executor, trade))
        return None
    trade.exit_fill_price = float(fill)
    lot_size = int(trade.signal.lot_size)
    pnl_gross = (trade.exit_fill_price - float(trade.fill_price or trade.signal.entry_premium)) * lot_size * int(trade.lots)
    charges = calculate_charges(premium=trade.exit_fill_price, lot_size=lot_size, lots=int(trade.lots), instrument=trade.signal.instrument.upper(), side="SELL")["total"]
    pnl_net = pnl_gross - float(charges)
    trade.trade_state = "CLOSED"
    executor.journal.log_exit(trade.trade_id, trade.exit_fill_price, str(trade.exit_reason or "MANUAL"), now, pnl_gross=pnl_gross, pnl_net=pnl_net, charges=charges)
    row = _live_row(executor, trade) | {"pnl_gross": pnl_gross, "pnl_net": pnl_net, "charges": float(charges), "timestamp_exit": now}
    upsert_live_trade(executor._engine, row)
    executor.capital_tracker.release_margin(trade.trade_id, pnl_net)
    executor._open.pop(trade.trade_id, None)
    logger.info("fill confirmed trade_id=%s fill_price=%.2f state=%s", trade.trade_id, trade.exit_fill_price, trade.trade_state)
    return {"trade_id": trade.trade_id, "instrument": trade.signal.instrument.upper(), "entry_time": trade.entry_time, "direction": trade.signal.direction, "option_type": trade.signal.option_type, "strike": trade.signal.strike, "expiry_date": trade.signal.expiry_date, "entry_premium": float(trade.fill_price or trade.signal.entry_premium), "exit_premium": trade.exit_fill_price, "exit_reason": str(trade.exit_reason or "MANUAL"), "lot_size": lot_size, "lots": int(trade.lots), "pnl_gross": pnl_gross, "pnl_net": pnl_net, "charges": float(charges), "confidence": float(trade.signal.confidence)}
