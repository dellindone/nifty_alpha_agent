import pandas as pd

from features.engineering import _filter_date_range, build_feature_frame


def _ohlcv(start, n, freq):
    i = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"open": range(100, 100 + n), "high": range(101, 101 + n), "low": range(99, 99 + n), "close": range(100, 100 + n), "volume": [1000] * n}, index=i)


def test_build_feature_frame_and_filter_end_date_behaviour():
    f5 = _ohlcv("2026-05-04 03:45:00+00:00", 80, "5min")
    f5["vix"] = 14.0
    frames = {"5m": f5, "15m": _ohlcv("2026-05-03 03:45:00+00:00", 60, "15min"), "60m": _ohlcv("2026-05-01 03:45:00+00:00", 60, "60min"), "D": _ohlcv("2026-03-01 00:00:00+00:00", 60, "1D")}
    out = build_feature_frame(frames, "NIFTY")
    assert isinstance(out.index, pd.DatetimeIndex) and str(out.index.tz) == "UTC"
    for c in ["close", "vix", "atr_14", "session_bar", "ema_stack_bull_15m", "trend_regime_60m", "bull_context_score", "market_context_score"]:
        assert c in out.columns
    date_only = _filter_date_range(out, end_date="2026-05-04")
    with_time = _filter_date_range(out, end_date="2026-05-04 23:59:59")
    assert pd.Timestamp("2026-05-04 03:45:00+00:00") in date_only.index
    assert len(with_time) >= len(date_only)
    assert out.iloc[-2].name == out.index[-2] and out.index[-2] < out.index[-1]
