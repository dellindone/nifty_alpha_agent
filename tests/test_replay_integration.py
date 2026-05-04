from datetime import datetime
from unittest.mock import patch

import pandas as pd

from replay import ReplayRunner
from model.predict import ModelPrediction


def test_check_open_trades_target_trail_eod_and_run(tmp_path):
    idx = pd.date_range("2026-05-04 03:45:00+00:00", periods=10, freq="5min", tz="UTC")
    bars = pd.DataFrame({"close": [100, 112, 130, 125, 111, 95, 100, 105, 110, 108], "session_bar": [6] * 10, "atr_14": [20.0] * 10, "vix": [14.0] * 10}, index=idx)
    p = tmp_path / "r.parquet"
    bars.to_parquet(p)
    with patch("replay.NiftyPredictor.load", return_value=None), patch("replay.TradeJournal"), patch("replay.CapitalTracker"), patch("replay.Reporter"):
        r = ReplayRunner("NIFTY", tmp_path, "2026-05-04", dataset_path=str(p), speed=0.0)
    T = lambda **k: type("T", (), k)()
    r._open_trades = [T(trade_id="a", direction=1, entry_close=100, entry_premium=110, sl_dist=10, target_dist=25, entry_bar=0, lots=1, bars_held=0, trail_active=False, trail_peak=0.0, trail_stop=0.0)]
    with patch.object(r.reporter, "_send", return_value=None):
        r._check_open_trades(130, datetime(2026, 5, 4, 9, 40))
    assert r._open_trades == []
    r._open_trades = [T(trade_id="b", direction=1, entry_close=100, entry_premium=110, sl_dist=10, target_dist=50, entry_bar=0, lots=1, bars_held=0, trail_active=False, trail_peak=0.0, trail_stop=0.0)]
    with patch.object(r.reporter, "_send", return_value=None):
        r._check_open_trades(112, datetime(2026, 5, 4, 9, 45)); r._check_open_trades(125, datetime(2026, 5, 4, 9, 50)); r._check_open_trades(111, datetime(2026, 5, 4, 9, 55))
    assert r._open_trades == []
    r._open_trades = [T(trade_id="c", direction=1, entry_close=100, entry_premium=110, sl_dist=10, target_dist=200, entry_bar=0, lots=1, bars_held=77, trail_active=False, trail_peak=0.0, trail_stop=0.0)]
    with patch.object(r.reporter, "_send", return_value=None):
        r._check_open_trades(101, datetime(2026, 5, 4, 15, 25))
    assert r._open_trades == []
    pred = ModelPrediction(1, 0.8, "MEDIUM", "WIDE", "15m", 60.0, 0.8, "CE_TP_FIRST", True)
    with patch.object(r.predictor, "predict", return_value=pred), patch("replay.synthetic_premium.compute", return_value=110.0), patch("replay.market_calendar.days_to_next_expiry", return_value=3), patch.object(r.reporter, "_send", return_value=None):
        r.run()
    assert r._trade_seq > 0
