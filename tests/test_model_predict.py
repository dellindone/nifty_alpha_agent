from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from config.settings import Paths
from model.predict import NiftyPredictor

PARQUET_PATH = Path(__file__).resolve().parents[3] / "trading_research/data/nifty/NIFTY_features_v5_oos_2026.parquet"
REFERENCE_TIMESTAMP = "2026-05-04 04:25:00+00:00"
EXPECTED_CLASS = "PE_TP_FIRST"
EXPECTED_DIRECTION = 0
EXPECTED_CONF_MIN = 0.50


def _row(cols, v=0.0):
    return pd.DataFrame([{c: v for c in cols}], index=[pd.Timestamp("2026-05-04 04:25:00", tz="UTC")])


def test_load_shadow_and_live_and_missing_dir():
    p = NiftyPredictor(); p.load(Paths.MODELS_SHADOW, "NIFTY")
    assert p.selected_features and all(isinstance(x, str) for x in p.selected_features)
    p2 = NiftyPredictor(); p2.load(Paths.MODELS_LIVE, "NIFTY")
    assert p2.selected_features
    with pytest.raises(FileNotFoundError):
        NiftyPredictor().load("/tmp/definitely_missing_models_dir_xyz", "NIFTY")


def test_predict_contract_determinism_and_robustness():
    p = NiftyPredictor(); p.load(Paths.MODELS_SHADOW, "NIFTY")
    x = _row(p.selected_features, 0.0)
    a = p.predict(x); b = p.predict(x)
    assert a == b
    assert a.trade_class in {"CE_TP_FIRST", "PE_TP_FIRST", "NO_TRADE"}
    assert a.direction in {0, 1} and 0.0 <= a.confidence <= 1.0
    assert a.sl_bin in {"TIGHT", "NARROW", "MEDIUM", "WIDE", "VERY_WIDE"}
    assert a.phase1_target > 0 and a.should_trade == (a.trade_class != "NO_TRADE")
    if a.trade_class == "CE_TP_FIRST": assert a.direction == 1
    if a.trade_class == "PE_TP_FIRST": assert a.direction == 0
    n = p.predict(_row(p.selected_features, np.nan))
    assert n.trade_class in {"CE_TP_FIRST", "PE_TP_FIRST", "NO_TRADE"} and isinstance(n.should_trade, bool)
    hi = p.predict(_row(p.selected_features, 1e9))
    assert hi is not None
    with pytest.raises(ValueError):
        p.predict(pd.DataFrame([{"close": 1.0}], index=[pd.Timestamp("2026-05-04 04:25:00", tz="UTC")]))


@pytest.mark.skipif(not PARQUET_PATH.exists(), reason="parquet not available")
def test_feature_drift_regression_guard_reference_bar():
    p = NiftyPredictor(); p.load(Paths.MODELS_SHADOW, "NIFTY")
    df = pd.read_parquet(PARQUET_PATH)
    if not isinstance(df.index, pd.DatetimeIndex): df.index = pd.to_datetime(df.index, utc=True)
    if df.index.tz is None: df.index = df.index.tz_localize("UTC")
    row = df.loc[[pd.Timestamp(REFERENCE_TIMESTAMP)]].reindex(columns=p.selected_features)
    pred = p.predict(row)
    assert pred.trade_class == EXPECTED_CLASS
    assert pred.direction == EXPECTED_DIRECTION
    assert pred.confidence >= EXPECTED_CONF_MIN
