import numpy as np
import pandas as pd


def compute_session_features(df: pd.DataFrame, opening_range_bars: int = 6) -> pd.DataFrame:
    featured = df.copy()
    if not isinstance(featured.index, pd.DatetimeIndex):
        return featured

    if featured.index.tz is None:
        local_index = featured.index.tz_localize("Asia/Kolkata")
    else:
        local_index = featured.index.tz_convert("Asia/Kolkata")

    session_dates = pd.Series(local_index.date, index=featured.index)
    session_minute = ((local_index.hour * 60) + local_index.minute) - (9 * 60 + 15)
    session_minute = pd.Series(session_minute, index=featured.index).clip(lower=0, upper=375)
    session_bar = featured.groupby(session_dates).cumcount()

    opening_range_high = pd.Series(np.nan, index=featured.index, dtype=float)
    opening_range_low = pd.Series(np.nan, index=featured.index, dtype=float)

    for _, session_frame in featured.groupby(session_dates):
        if len(session_frame) == 0:
            continue
        opening_slice = session_frame.iloc[:opening_range_bars]
        or_high = float(opening_slice["high"].max())
        or_low = float(opening_slice["low"].min())
        # Fill all bars — early bars use running session high/low as OR proxy
        opening_range_high.loc[session_frame.index] = or_high
        opening_range_low.loc[session_frame.index] = or_low

    atr_base = pd.to_numeric(featured.get("atr_14"), errors="coerce").replace(0.0, np.nan)
    featured["session_minute"] = session_minute.astype(int)
    featured["session_bar"] = session_bar.astype(int)
    featured["opening_range_high"] = opening_range_high
    featured["opening_range_low"] = opening_range_low
    featured["opening_range_width_atr"] = (opening_range_high - opening_range_low) / atr_base
    featured["above_opening_range"] = (
        opening_range_high.notna() & (featured["close"] > opening_range_high)
    ).astype(int)
    featured["below_opening_range"] = (
        opening_range_low.notna() & (featured["close"] < opening_range_low)
    ).astype(int)
    featured["dist_to_or_high_atr"] = (opening_range_high - featured["close"]) / atr_base
    featured["dist_to_or_low_atr"] = (featured["close"] - opening_range_low) / atr_base

    time_bucket = pd.Series(1, index=featured.index, dtype=int)
    time_bucket[session_minute <= 60] = 0
    time_bucket[session_minute >= 240] = 2
    featured["time_bucket"] = time_bucket.astype(int)

    return featured
