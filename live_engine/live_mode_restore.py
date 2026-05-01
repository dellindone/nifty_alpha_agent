import logging

import pandas as pd

from lib.signal_handler import TradeSignal
from live_mode_types import LiveTrade

logger = logging.getLogger(__name__)


def restore_open_trades(executor) -> None:
    try:
        df = executor.journal.load_open_trades()
    except Exception as exc:
        logger.warning("restore_open_trades_failed error=%s", exc); return
    if getattr(df, "empty", True):
        return
    for _, row in df.iterrows():
        try:
            if str(row.get("broker_name") or "") != executor.broker_name or str(row.get("account_name") or "") != executor.account_name: continue
            req = ["trade_id", "instrument", "entry_premium", "sl_price", "target_price", "timestamp_entry", "expiry_date", "option_type", "strike", "direction", "confidence", "direction_prob", "trail_bin", "trail_tf", "lot_size", "lots"]
            if any(pd.isna(row.get(k)) for k in req): logger.warning("restore_skip trade_id=%s", row.get("trade_id")); continue
            signal = TradeSignal(instrument=str(row["instrument"]).upper(), direction=int(row["direction"]), option_type=str(row["option_type"]), strike=int(float(row["strike"])), expiry_date=pd.to_datetime(row["expiry_date"]).date(), entry_premium=float(row["entry_premium"]), sl_price=float(row["sl_price"]), target_price=float(row["target_price"]), trail_bin=str(row["trail_bin"]), trail_tf=str(row["trail_tf"]), confidence=float(row["confidence"]), direction_prob=float(row["direction_prob"]), vix=float(row.get("vix_at_entry") or 0.0), atr=float(row.get("atr_at_entry") or 0.0), lot_size=int(float(row["lot_size"])), lots=int(float(row["lots"])))
            trade = LiveTrade(trade_id=str(row["trade_id"]), signal=signal, entry_time=pd.to_datetime(row["timestamp_entry"]).to_pydatetime(), current_sl=float(row.get("current_sl")) if pd.notna(row.get("current_sl")) else float(row["entry_premium"]) - float(row["sl_price"]), highest_premium=float(row.get("highest_premium")) if pd.notna(row.get("highest_premium")) else float(row["entry_premium"]), current_target=float(row.get("target_price")) + float(row["entry_premium"]), option_symbol="", trade_state="OPEN", broker_order_id=str(row.get("broker_order_id") or ""), fill_price=float(row["entry_premium"]), trail_active=bool(row.get("trail_active")), lots=int(float(row["lots"])))
            executor._open[trade.trade_id] = trade; logger.warning("restored_live_trade trade_id=%s broker=%s account=%s", trade.trade_id, executor.broker_name, executor.account_name)
        except Exception:
            logger.warning("restore_skip trade_id=%s", row.get("trade_id"))
