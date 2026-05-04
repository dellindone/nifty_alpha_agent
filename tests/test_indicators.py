import numpy as np
import pandas as pd

from features.indicators import realized_volatility, rsi, zscore


def test_rsi_up_regime():
    returns = [1.0 if i % 6 else -0.2 for i in range(40)]
    series = pd.Series(100 + np.cumsum(returns), dtype=float)
    out = rsi(series, 14).dropna()
    assert not out.empty
    assert out.iloc[-1] > 70


def test_rsi_down_regime():
    returns = [-1.0 if i % 6 else 0.2 for i in range(40)]
    series = pd.Series(200 + np.cumsum(returns), dtype=float)
    out = rsi(series, 14).dropna()
    assert not out.empty
    assert out.iloc[-1] < 30


def test_rsi_flat_regime():
    series = pd.Series([100.0 + (0.05 if i % 2 else -0.05) for i in range(40)], dtype=float)
    out = rsi(series, 14).dropna()
    assert not out.empty
    assert ((out >= 0) & (out <= 100)).all()


def test_rsi_short_window():
    series = pd.Series(range(1, 41), dtype=float)
    out = rsi(series, 5)
    assert len(out) == len(series)


def test_zscore_known_value():
    out = zscore(pd.Series([1.0, 2.0, 3.0, 4.0, 5.0]), 3)
    assert np.isclose(out.iloc[-1], (5 - 4) / np.std([3, 4, 5], ddof=1))


def test_zscore_constant_series():
    out = zscore(pd.Series([10.0] * 5), 3)
    assert out.isna().all()


def test_realized_volatility_shape():
    out = realized_volatility(pd.Series([100, 101, 100, 102, 103], dtype=float), 3, 252)
    assert len(out) == 5
