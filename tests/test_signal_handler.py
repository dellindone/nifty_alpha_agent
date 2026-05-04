from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from lib.signal_handler import SignalHandler, lots_for_day
from model.predict import ModelPrediction


def _pred(**k):
    d = dict(direction=1, direction_prob=0.7, sl_bin="MEDIUM", trail_bin="WIDE", trail_tf="15m", phase1_target=30.0,
             confidence=0.8, trade_class="CE_TP_FIRST", should_trade=True)
    d.update(k)
    return ModelPrediction(**d)


def _row(**k):
    d = {"session_bar": 6, "vix": 14.0, "atr_14": 20.0, "close": 22500.0}
    d.update(k)
    return pd.DataFrame([d], index=[pd.Timestamp("2026-05-04 04:00:00", tz="UTC")])


@pytest.mark.parametrize(
    "kw,row_kw,extra,reason",
    [
        ({"should_trade": False}, {}, {}, "MODEL_NO_TRADE"),
        ({}, {}, {"open_trade_count": 1}, "TRADE_ALREADY_OPEN"),
        ({}, {"session_bar": 5}, {}, "TOO_EARLY"),
        ({"confidence": 0.54}, {}, {}, "LOW_CONF"),
        ({}, {}, {"daily_pnl": -2500}, "DAILY_LOSS_LIMIT"),
        ({}, {}, {"daily_pnl": 5000}, "DAILY_TARGET_HIT"),
        ({}, {"atr_14": 0.0}, {}, "ZERO_ATR"),
        ({"phase1_target": 2.0}, {}, {}, "LOW_RR"),
    ],
)
def test_process_blocks(kw, row_kw, extra, reason):
    h = SignalHandler()
    with patch("lib.signal_handler.option_chain_service.get_best_instrument", return_value={"processed": [1], "atm": 22500, "expiry": date(2026, 5, 7)}), \
         patch("lib.signal_handler.strike_selector.select", return_value={"lp": 120.0, "strike": 22400}):
        out = h.process(_pred(**kw), _row(**row_kw), "NIFTY", **extra)
    assert out is None
    assert reason in h.last_block_reason


def test_process_max_trades_returns_blocked_signal():
    h = SignalHandler()
    with patch("lib.signal_handler.option_chain_service.get_best_instrument", return_value={"processed": [1], "atm": 22500, "expiry": date(2026, 5, 7)}), \
         patch("lib.signal_handler.strike_selector.select", return_value={"lp": 120.0, "strike": 22400}):
        out = h.process(_pred(phase1_target=60.0), _row(), "NIFTY", daily_trade_count=6)
    assert out is not None and out.blocked is True
    assert "MAX_TRADES" in out.block_reason


def test_process_happy_path_and_lots_for_day_tiers():
    h = SignalHandler()
    with patch("lib.signal_handler.option_chain_service.get_best_instrument", return_value={"processed": [1], "atm": 22500, "expiry": date(2026, 5, 7)}), \
         patch("lib.signal_handler.strike_selector.select", return_value={"lp": 120.0, "strike": 22400}):
        out = h.process(_pred(phase1_target=60.0), _row(), "NIFTY")
    assert out.instrument == "NIFTY" and out.option_type == "CE" and out.strike == 22400
    assert out.entry_premium == 120.0 and out.sl_price > 0 and out.target_price == 60.0 and out.lots == 1
    assert lots_for_day(0, 5000) == 3
    assert lots_for_day(2500, 5000) == 2
    assert lots_for_day(3800, 5000) == 1
    assert lots_for_day(5000, 5000) == 0 and lots_for_day(6000, 5000) == 0
