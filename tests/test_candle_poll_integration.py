from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from candle_poll import CandlePoll
from model.predict import ModelPrediction


class _L:
    def __enter__(self): return self
    def __exit__(self, a, b, c): return False


def _engine():
    e = SimpleNamespace()
    e._tick_lock = _L(); e._poll_count = 0; e.instrument = "NIFTY"; e._last_decision = ""; e._daily_target_alerted_on = None
    e._last_pred_data = {}; e._last_vix = e._last_atr = e._last_daily_pnl = 0.0; e._last_daily_count = 0
    e.health = SimpleNamespace(update=MagicMock()); e.executor = SimpleNamespace(cancel_expired_pending=lambda _: [], open_trades=lambda: [])
    e._unsubscribe_if_unused = MagicMock(); e._log_poll = MagicMock(); e._print_live_display = MagicMock()
    e.predictor = SimpleNamespace(selected_features=["close", "vix", "atr_14", "session_bar"], predict=MagicMock())
    e.signal_handler = SimpleNamespace(process=MagicMock(), last_block_reason="")
    e.journal = SimpleNamespace(open_trades=lambda: [], load_all=lambda: pd.DataFrame())
    e.reporter = SimpleNamespace(send_daily_target_alert=MagicMock(), _send=MagicMock(), send_signal_alert=MagicMock())
    e._build_no_signal_decision = lambda p: "NO_SIGNAL"; e._handle_trade_signal = MagicMock(return_value="CE")
    return e


def test_candle_poll_end_to_end_paths():
    e = _engine(); cp = CandlePoll(e)
    idx = pd.DatetimeIndex([pd.Timestamp("2026-05-04 04:00:00", tz="UTC"), pd.Timestamp("2026-05-04 04:05:00", tz="UTC")])
    ff = pd.DataFrame({"close": [22500, 22510], "vix": [14.0, 14.0], "atr_14": [20.0, 20.0], "session_bar": [6, 7]}, index=idx)
    pred = ModelPrediction(1, 0.7, "MEDIUM", "WIDE", "15m", 60.0, 0.8, "CE_TP_FIRST", True)
    e.predictor.predict.return_value = pred; e.signal_handler.process.return_value = SimpleNamespace(blocked=False)
    with patch.object(cp, "_fetch_live_frames", return_value={"5m": ff}), patch("candle_poll.build_feature_frame", return_value=ff):
        cp._run_candle_poll(datetime(2026, 5, 4, 10, 0))
    e.signal_handler.process.assert_called_once()
    k = e.signal_handler.process.call_args.kwargs
    assert k["instrument"] == "NIFTY" and "daily_pnl" in k and "daily_trade_count" in k
    assert k["open_trade_count"] == 0
    e._handle_trade_signal.assert_called_once()
    assert e.predictor.predict.call_args.args[0].index[0] == ff.index[-2]
    e.signal_handler.process.reset_mock()
    e.executor.open_trades = lambda: [object()]
    e.journal.open_trades = lambda: []
    with patch.object(cp, "_fetch_live_frames", return_value={"5m": ff}), patch("candle_poll.build_feature_frame", return_value=ff):
        cp._run_candle_poll(datetime(2026, 5, 4, 10, 5))
    assert e.signal_handler.process.call_args.kwargs["open_trade_count"] == 1
    e.signal_handler.process.reset_mock(); e._handle_trade_signal.reset_mock()
    with patch.object(cp, "_fetch_live_frames", return_value={"5m": ff}), patch("candle_poll.build_feature_frame", return_value=pd.DataFrame()):
        cp._run_candle_poll(datetime(2026, 5, 4, 10, 0))
    assert e._last_decision == "NO_FEATURE_ROW" and e.signal_handler.process.call_count == 0
    with patch.object(cp, "_fetch_live_frames", side_effect=Exception("boom")), patch.object(e.reporter, "_send"):
        cp._run_candle_poll(datetime(2026, 5, 4, 10, 0))
    assert any(c.args[1] == "critical" for c in e.health.update.call_args_list)
    e.signal_handler.process.reset_mock()
    with patch.object(cp, "_fetch_live_frames", return_value={"5m": ff}), patch("candle_poll.build_feature_frame", return_value=ff), patch.object(e.reporter, "_send"):
        cp._run_candle_poll(datetime(2026, 5, 4, 15, 16))
    e.signal_handler.process.assert_not_called()
    assert e.signal_handler.last_block_reason == "NO_NEW_TRADES_AFTER_15:15"
