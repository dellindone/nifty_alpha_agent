import datetime as dt

import numpy as np
import pandas as pd

from db import _coerce_timestamp, _is_nat_or_nan, _normalize_record


def test_is_nat_or_nan():
    assert _is_nat_or_nan(pd.NaT) is True
    assert _is_nat_or_nan(float("nan")) is True
    assert _is_nat_or_nan(None) is False
    assert _is_nat_or_nan(dt.datetime.now()) is False


def test_coerce_timestamp_cases():
    assert _coerce_timestamp(None) is None
    assert _coerce_timestamp(pd.NaT) is None
    naive_local = _coerce_timestamp("2026-05-04T09:15:00")
    assert isinstance(naive_local, dt.datetime)
    assert naive_local == dt.datetime(2026, 5, 4, 9, 15)
    x = dt.datetime(2026, 5, 4, 9, 15)
    assert _coerce_timestamp(x) == x
    utc_value = dt.datetime(2026, 5, 4, 4, 0, tzinfo=dt.timezone.utc)
    assert _coerce_timestamp(utc_value) == dt.datetime(2026, 5, 4, 9, 30)


def test_normalize_record_converts_aware_timestamps_to_ist_naive():
    normalized = _normalize_record({"timestamp_entry": dt.datetime(2026, 5, 4, 4, 0, tzinfo=dt.timezone.utc)})
    assert normalized["timestamp_entry"] == dt.datetime(2026, 5, 4, 9, 30)


def test_normalize_record_scalars_and_dates():
    r = {
        "timestamp_entry": "2026-05-04T09:15:00",
        "timestamp_exit": pd.NaT,
        "expiry_date": pd.Timestamp("2026-05-08"),
        "lots": np.int64(2),
        "confidence": np.float32(0.55),
    }
    n = _normalize_record(r)
    assert isinstance(n["lots"], int) and isinstance(n["confidence"], float)
    assert n["timestamp_exit"] is None and str(n["expiry_date"])[:10] == "2026-05-08"
    n2 = _normalize_record({"timestamp_entry": None, "timestamp_exit": None, "expiry_date": pd.NaT})
    assert n2["expiry_date"] is None
