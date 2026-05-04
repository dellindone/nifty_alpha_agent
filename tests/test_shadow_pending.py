import datetime as dt
from unittest.mock import MagicMock

from lib.signal_handler import TradeSignal
from shadow_mode import ShadowMode


def _sig():
    return TradeSignal("NIFTY", 1, "CE", 22400, dt.date(2026, 5, 8), 100.0, 20.0, 30.0, "WIDE", "15m", 0.7, 0.6, 14.0, 20.0, 65, 1)


def _mode():
    j = MagicMock(); j.load_open_trades.return_value = j.load_all.return_value = __import__("pandas").DataFrame()
    c = MagicMock(); c.get_available_capital.return_value = 1e9; c.reserve_margin.return_value = True
    return ShadowMode(j, c), j


def test_set_pending_and_get_pending_symbols():
    sm, _ = _mode()
    p = sm.set_pending(_sig(), "NSE:NIFTYCE")
    assert p is not None and sm.get_pending_symbols() == ["NSE:NIFTYCE"]
    sm.set_pending(_sig(), "NSE:NIFTYCE")
    assert sm.get_pending_symbols() == ["NSE:NIFTYCE"]


def test_check_pending_fill_fills_and_clears():
    sm, j = _mode(); s = _sig(); sm.set_pending(s, "NSE:NIFTYCE")
    t = sm.check_pending_fill("NSE:NIFTYCE", 99.0, dt.datetime.now(dt.timezone.utc))
    assert t is not None and sm.get_pending_symbols() == []
    assert j.log_entry.called


def test_check_pending_fill_not_filled_stays_pending():
    sm, j = _mode(); sm.set_pending(_sig(), "NSE:NIFTYCE")
    t = sm.check_pending_fill("NSE:NIFTYCE", 120.0, dt.datetime.now(dt.timezone.utc))
    assert t is None and sm.get_pending_symbols() == ["NSE:NIFTYCE"]
    assert not j.log_entry.called


def test_cancel_expired_pending_and_empty_symbols():
    sm, _ = _mode(); sm.set_pending(_sig(), "NSE:NIFTYCE")
    now = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=20)
    expired = sm.cancel_expired_pending(now)
    assert expired == ["NSE:NIFTYCE"] and sm.get_pending_symbols() == []


def test_close_trade_exit_reasons_from_tick():
    sm, j = _mode(); tr = sm.enter_trade(_sig(), "NSE:NIFTYCE")
    out = sm.tick("NIFTY", tr.current_sl - 1, dt.datetime.now(dt.timezone.utc))
    assert out and out[0]["exit_reason"] == "SL_HIT"
    sm.enter_trade(_sig(), "NSE:NIFTYCE")
    out2 = sm.tick("NIFTY", 131.0, dt.datetime.now(dt.timezone.utc))
    assert out2 and out2[0]["exit_reason"] == "TARGET_HIT"
    assert j.log_exit.called
