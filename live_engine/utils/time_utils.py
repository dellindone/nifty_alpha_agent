from __future__ import annotations

from datetime import datetime

import pandas as pd

from config.settings import IST


def is_null_timestamp(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except Exception:
        return False


def to_ist_aware_datetime(value: object) -> datetime | None:
    if is_null_timestamp(value):
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize(IST)
    else:
        ts = ts.tz_convert(IST)
    return ts.to_pydatetime()


def to_ist_naive_datetime(value: object) -> datetime | None:
    localized = to_ist_aware_datetime(value)
    if localized is None:
        return None
    return localized.replace(tzinfo=None)


def to_ist_series(values: pd.Series) -> pd.Series:
    def _convert(value: object) -> pd.Timestamp:
        localized = to_ist_aware_datetime(value)
        return pd.Timestamp(localized) if localized is not None else pd.NaT

    return values.apply(_convert)
