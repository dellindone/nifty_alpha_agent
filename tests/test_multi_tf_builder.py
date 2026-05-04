import pandas as pd

from config.settings import Paths
from ingestion.multi_tf_builder import MultiTFBuilder, _filter_nse_session, _normalize_columns


def _frame(start="2026-05-04 03:00:00+00:00", n=30, freq="5min"):
    i = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"Open": range(n), "High": range(1, n + 1), "Low": range(n), "Close": range(n), "Volume": [100] * n}, index=i)


def test_normalize_and_filter_session():
    n = _normalize_columns(_frame())
    assert list(n.columns) == ["open", "high", "low", "close", "volume"]
    f = _filter_nse_session(n, "5m")
    assert not f.empty
    assert all((t.hour * 60 + t.minute) >= 555 for t in f.index.tz_convert("Asia/Kolkata"))


def test_build_and_attach_vix(monkeypatch, tmp_path):
    b = MultiTFBuilder()
    src = {"5m": _frame("2026-05-04 03:45:00+00:00", 50, "5min"), "15m": _frame("2026-05-04 03:45:00+00:00", 50, "15min"), "60m": _frame("2026-05-01 03:45:00+00:00", 50, "60min"), "D": _frame("2026-03-01 00:00:00+00:00", 50, "1D")}
    for f in ["NIFTY_5.parquet", "NIFTY_15.parquet", "NIFTY_60.parquet", "NIFTY_D.parquet", "INDIAVIX_5.parquet"]:
        (tmp_path / f).touch()
    vix = pd.DataFrame({"close": [14.0] * 50}, index=src["5m"].index)
    monkeypatch.setitem(Paths.DATA_DIRS, "nifty", tmp_path)
    monkeypatch.setattr(b, "_load_frame", lambda p, tf: vix if "INDIAVIX_5.parquet" in str(p) else src[tf])
    out = b.build("NIFTY")
    assert {"5m", "15m", "60m", "D"} <= set(out)
    assert "vix" in out["5m"].columns
