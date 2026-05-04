from datetime import date, datetime
from unittest.mock import patch

import pandas as pd

from replay import ReplayRunner
from model.predict import ModelPrediction


def _bars(day="2026-05-04", n=5):
    idx = pd.date_range(f"{day} 03:45:00+00:00", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({"close": [22500 + i for i in range(n)], "session_bar": [6 + i for i in range(n)], "atr_14": [20.0] * n, "vix": [14.0] * n}, index=idx)


def _pred(**k):
    d = dict(direction=1, direction_prob=0.8, sl_bin="MEDIUM", trail_bin="WIDE", trail_tf="15m", phase1_target=30.0,
             confidence=0.8, trade_class="CE_TP_FIRST", should_trade=True)
    d.update(k)
    return ModelPrediction(**d)


def _mk(tmp_path, day="2026-05-04"):
    p = tmp_path / "r.parquet"
    pd.concat([_bars(day), _bars("2026-05-03", 2)]).to_parquet(p)
    with patch("replay.NiftyPredictor.load", return_value=None), patch("replay.TradeJournal"), patch("replay.CapitalTracker"), patch("replay.Reporter"):
        return ReplayRunner("NIFTY", tmp_path, day, dataset_path=str(p), speed=0.0)


def test_load_bars_and_make_signal_filters(tmp_path):
    r = _mk(tmp_path)
    assert len(r._load_bars()) == 5
    r.replay_date = "2026-05-02"
    assert r._load_bars().empty
    row, now = _bars().iloc[0], datetime(2026, 5, 4, 9, 30)
    r._open_trades = [object()]
    assert r._make_signal(_pred(), row, now, 0.0, 0)[1].startswith("TRADE_ALREADY_OPEN")
    r._open_trades = []
    assert r._make_signal(_pred(should_trade=False), row, now, 0.0, 0)[1] == "MODEL_NO_TRADE"
    assert r._make_signal(_pred(), row.copy().rename("x").to_frame().T.assign(session_bar=5).iloc[0], now, 0.0, 0)[1].startswith("TOO_EARLY")
    assert r._make_signal(_pred(phase1_target=1.0), row, now, 0.0, 0)[1].startswith("LOW_RR")


def test_make_signal_happy_and_open_trade_exits(tmp_path):
    r = _mk(tmp_path)
    row, now = _bars().iloc[0], datetime(2026, 5, 4, 9, 30)
    with patch("replay.synthetic_premium.compute", return_value=110.0), patch("replay.market_calendar.days_to_next_expiry", return_value=3):
        sig, reason = r._make_signal(_pred(phase1_target=60.0), row, now, 0.0, 0)
    assert reason == "" and sig.strike == 22400 and sig.option_type == "CE"
    r._open_trades = [type("T", (), dict(trade_id="1", direction=1, entry_close=100, entry_premium=120, sl_dist=10, target_dist=20, entry_bar=0, lots=1, bars_held=0, trail_active=False, trail_peak=0.0, trail_stop=0.0))()]
    with patch.object(r.reporter, "_send", return_value=None):
        r._check_open_trades(89, now)
    assert r._open_trades == []
