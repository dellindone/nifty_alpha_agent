from dataclasses import dataclass
from datetime import datetime

from lib.signal_handler import TradeSignal


@dataclass
class LiveTrade:
    trade_id: str
    signal: TradeSignal
    entry_time: datetime
    current_sl: float
    highest_premium: float
    current_target: float
    option_symbol: str
    trade_state: str = "PENDING"
    broker_order_id: str | None = None
    broker_exit_order_id: str | None = None
    fill_price: float | None = None
    exit_fill_price: float | None = None
    exit_reason: str | None = None
    trail_active: bool = False
    lots: int = 1
