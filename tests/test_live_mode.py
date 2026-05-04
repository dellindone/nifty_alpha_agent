from datetime import date, datetime, timezone
from unittest.mock import MagicMock
import pandas as pd
import live_mode
import live_mode_fills
from lib.signal_handler import TradeSignal
class FakeBroker:
    def __init__(self):
        self.orders = []
        self.entry_fill = None
        self.exit_fill = None
        self.status = "PENDING"

    def place_order(self, symbol, qty, transaction_type, order_type, segment, product, price=0.0):
        self.orders.append((symbol, qty, transaction_type.value, order_type.value))
        return {"order_id": f"O{len(self.orders)}"}

    def get_order_executed_price(self, order_id, segment):
        return self.exit_fill if order_id == "O2" else self.entry_fill

    def get_order_status(self, order_id, segment):
        return self.status

    def cancel_order(self, order_id):
        self.orders.append(("CANCEL", order_id))
        return {"id": order_id}
def _signal():
    return TradeSignal(instrument="NIFTY", direction=1, option_type="CE", strike=25000, expiry_date=date(2026, 5, 1), entry_premium=100.0, sl_price=20.0, target_price=40.0, trail_bin="MEDIUM", trail_tf="15m", confidence=0.7, direction_prob=0.8, vix=15.0, atr=20.0, lot_size=65, lots=1)


def test_live_mode_entry_sl_and_force_close(monkeypatch):
    broker, writes = FakeBroker(), []
    monkeypatch.setattr(live_mode, "get_engine", lambda: None)
    monkeypatch.setattr(live_mode.BrokerFactory, "create", lambda name: broker)
    monkeypatch.setattr(live_mode.Trading, "BROKER_NAME", "fyers")
    monkeypatch.setattr(live_mode.Trading, "ACCOUNT_NAME", "nifty_fyers_main")
    monkeypatch.setattr(live_mode_fills, "upsert_live_trade", lambda engine, row: writes.append(row.copy()))
    journal, capital = MagicMock(), MagicMock()
    capital.get_available_capital.return_value = 1_000_000
    capital.reserve_margin.return_value = True
    ex = live_mode.LiveModeExecutor(journal=journal, capital_tracker=capital)
    assert ex.set_pending(_signal(), "") is None
    ex.set_pending(_signal(), "NSE:NIFTY25JUN25000CE")
    assert ex.enter_trade(_signal(), "NSE:NIFTY25JUN25000CE") is None
    trade = ex.check_pending_fill("NSE:NIFTY25JUN25000CE", 100.0, datetime.now(timezone.utc))
    assert trade.trade_state == "PENDING" and broker.orders[0][2:] == ("BUY", "MARKET")
    broker.entry_fill, broker.status = None, "TRANSIT"
    ex.tick("NIFTY", 100.0, datetime.now(timezone.utc))
    assert ex.open_trades()[0].trade_state == "PENDING"
    broker.entry_fill, broker.status = 101.0, "FILLED"
    ex.tick("NIFTY", 101.0, datetime.now(timezone.utc))
    trade = ex.open_trades()[0]
    assert trade.trade_state == "OPEN" and trade.fill_price == 101.0
    assert ex.enter_trade(_signal(), "NSE:NIFTY25JUN25000CE") is None
    broker.exit_fill, broker.status = None, "PENDING"
    ex.tick("NIFTY", 80.0, datetime.now(timezone.utc))
    trade = ex.open_trades()[0]
    assert trade.trade_state == "SL_HIT" and broker.orders[-1][2:] == ("SELL", "MARKET")
    broker.exit_fill, broker.status = 79.0, "FILLED"
    closed = ex.force_close_all({"NIFTY": 79.0})
    assert closed and not ex.open_trades()
    assert writes[-1]["account_name"] == "nifty_fyers_main" and writes[-1]["broker_name"] == "fyers"
    trade = ex.enter_trade(_signal(), "NSE:NIFTY25JUN25000CE")
    broker.entry_fill, broker.status = 102.0, "FILLED"
    ex.tick("NIFTY", 102.0, datetime.now(timezone.utc))
    broker.exit_fill, broker.status = 103.0, "FILLED"
    assert ex.force_close_all({"NIFTY": 103.0})
def test_live_mode_expiry_and_failed_paths(monkeypatch):
    broker, writes = FakeBroker(), []
    monkeypatch.setattr(live_mode, "get_engine", lambda: None)
    monkeypatch.setattr(live_mode.BrokerFactory, "create", lambda name: broker)
    monkeypatch.setattr(live_mode.Trading, "BROKER_NAME", "groww")
    monkeypatch.setattr(live_mode.Trading, "ACCOUNT_NAME", "acc1")
    monkeypatch.setattr(live_mode_fills, "upsert_live_trade", lambda engine, row: writes.append(row.copy()))
    journal, capital = MagicMock(), MagicMock()
    capital.get_available_capital.return_value = 0
    capital.reserve_margin.return_value = False
    ex = live_mode.LiveModeExecutor(journal=journal, capital_tracker=capital)
    ex.set_pending(_signal(), "NSE:NIFTY25JUN25000CE")
    assert ex.cancel_expired_pending(datetime.now(timezone.utc).replace(year=2030))
    capital.get_available_capital.return_value = 1_000_000
    capital.reserve_margin.return_value = True
    ex.set_pending(_signal(), "NSE:NIFTY25JUN25000CE")
    trade = ex.check_pending_fill("NSE:NIFTY25JUN25000CE", 100.0, datetime.now(timezone.utc))
    broker.entry_fill, broker.status = None, "REJECTED"
    assert ex.tick("NIFTY", 100.0, datetime.now(timezone.utc)) == []
    assert not ex.open_trades() and writes[-1]["trade_state"] == "FAILED"
    capital.release_margin.assert_called_once_with(trade.trade_id, 0.0)
def test_pending_order_cancelled_at_eod(monkeypatch):
    broker, writes = FakeBroker(), []
    monkeypatch.setattr(live_mode, "get_engine", lambda: None)
    monkeypatch.setattr(live_mode.BrokerFactory, "create", lambda name: broker)
    monkeypatch.setattr(live_mode.Trading, "BROKER_NAME", "fyers")
    monkeypatch.setattr(live_mode.Trading, "ACCOUNT_NAME", "acc1")
    monkeypatch.setattr(live_mode_fills, "upsert_live_trade", lambda engine, row: writes.append(row.copy()))
    monkeypatch.setattr(live_mode, "upsert_live_trade", lambda engine, row: writes.append(row.copy()))
    journal, capital = MagicMock(), MagicMock()
    capital.get_available_capital.return_value = 1_000_000
    capital.reserve_margin.return_value = True
    ex = live_mode.LiveModeExecutor(journal=journal, capital_tracker=capital)
    ex.set_pending(_signal(), "NSE:NIFTY25JUN25000CE")
    ex.check_pending_fill("NSE:NIFTY25JUN25000CE", 100.0, datetime.now(timezone.utc))
    broker.entry_fill, broker.status = None, "TRANSIT"
    assert ex.force_close_all({}) == []
    assert not ex.open_trades() and broker.orders[-1][0] == "CANCEL" and writes[-1]["trade_state"] == "FAILED"
    capital.release_margin.assert_called_once()
def test_restore_open_trades_on_init(monkeypatch):
    broker = FakeBroker()
    monkeypatch.setattr(live_mode, "get_engine", lambda: None)
    monkeypatch.setattr(live_mode.BrokerFactory, "create", lambda name: broker)
    monkeypatch.setattr(live_mode.Trading, "BROKER_NAME", "fyers")
    monkeypatch.setattr(live_mode.Trading, "ACCOUNT_NAME", "acc1")
    journal, capital = MagicMock(), MagicMock()
    journal.load_open_trades.return_value = pd.DataFrame([{"trade_id": "t1", "broker_name": "fyers", "account_name": "acc1", "instrument": "NIFTY", "entry_premium": 101.0, "sl_price": 20.0, "target_price": 40.0, "timestamp_entry": datetime.now(timezone.utc), "expiry_date": date(2026, 5, 1), "option_type": "CE", "strike": 25000, "direction": 1, "confidence": 0.7, "direction_prob": 0.8, "trail_bin": "MEDIUM", "trail_tf": "15m", "lot_size": 65, "lots": 1, "current_sl": 90.0, "highest_premium": 110.0, "trail_active": True, "broker_order_id": "OID1"}])
    ex = live_mode.LiveModeExecutor(journal=journal, capital_tracker=capital)
    trade = ex.open_trades()[0]
    assert len(ex.open_trades()) == 1 and trade.trade_state == "OPEN" and trade.fill_price == 101.0 and trade.broker_order_id == "OID1"
