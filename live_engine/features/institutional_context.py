import numpy as np
import pandas as pd


def _safe_atr_base(df: pd.DataFrame) -> pd.Series:
    atr_base = pd.to_numeric(df.get("atr_14"), errors="coerce")
    if atr_base is None:
        atr_base = pd.Series(np.nan, index=df.index, dtype=float)
    return atr_base.replace(0.0, np.nan)


def _previous_day_levels(index: pd.DatetimeIndex, series: pd.Series) -> pd.Series:
    if index.tz is None:
        local_index = index.tz_localize("Asia/Kolkata")
    else:
        local_index = index.tz_convert("Asia/Kolkata")
    session_dates = pd.Series(local_index.date, index=index)
    daily_level = series.groupby(session_dates).transform("max")
    previous_level = daily_level.groupby(session_dates).transform("first")
    daily_lookup = previous_level.groupby(session_dates).first().shift(1)
    return session_dates.map(daily_lookup).astype(float)


def _previous_day_low(index: pd.DatetimeIndex, series: pd.Series) -> pd.Series:
    if index.tz is None:
        local_index = index.tz_localize("Asia/Kolkata")
    else:
        local_index = index.tz_convert("Asia/Kolkata")
    session_dates = pd.Series(local_index.date, index=index)
    daily_level = series.groupby(session_dates).transform("min")
    previous_level = daily_level.groupby(session_dates).transform("first")
    daily_lookup = previous_level.groupby(session_dates).first().shift(1)
    return session_dates.map(daily_lookup).astype(float)


def compute_institutional_context(df: pd.DataFrame) -> pd.DataFrame:
    featured = df.copy()
    atr_base = _safe_atr_base(featured)

    prior_high_10 = featured["high"].shift(1).rolling(10, min_periods=3).max()
    prior_low_10 = featured["low"].shift(1).rolling(10, min_periods=3).min()
    prior_high_20 = featured["high"].shift(1).rolling(20, min_periods=5).max()
    prior_low_20 = featured["low"].shift(1).rolling(20, min_periods=5).min()

    featured["prior_range_high_10"] = prior_high_10
    featured["prior_range_low_10"] = prior_low_10
    featured["dist_to_range_high_10_atr"] = (prior_high_10 - featured["close"]) / atr_base
    featured["dist_to_range_low_10_atr"] = (featured["close"] - prior_low_10) / atr_base
    featured["dist_to_range_high_20_atr"] = (prior_high_20 - featured["close"]) / atr_base
    featured["dist_to_range_low_20_atr"] = (featured["close"] - prior_low_20) / atr_base

    featured["structure_break_up_10"] = (featured["close"] > prior_high_10).astype(int)
    featured["structure_break_down_10"] = (featured["close"] < prior_low_10).astype(int)
    featured["liquidity_sweep_high_20"] = (
        (featured["high"] > prior_high_20) & (featured["close"] <= prior_high_20)
    ).astype(int)
    featured["liquidity_sweep_low_20"] = (
        (featured["low"] < prior_low_20) & (featured["close"] >= prior_low_20)
    ).astype(int)

    body = (featured["close"] - featured["open"]).abs()
    candle_range = (featured["high"] - featured["low"]).replace(0.0, np.nan)
    close_near_high = ((featured["high"] - featured["close"]) / candle_range).fillna(1.0)
    close_near_low = ((featured["close"] - featured["low"]) / candle_range).fillna(1.0)

    featured["displacement_up"] = (
        (featured["close"] > featured["open"])
        & (body >= (0.75 * atr_base))
        & (close_near_high <= 0.25)
    ).astype(int)
    featured["displacement_down"] = (
        (featured["close"] < featured["open"])
        & (body >= (0.75 * atr_base))
        & (close_near_low <= 0.25)
    ).astype(int)

    bull_gap = (featured["low"] - featured["high"].shift(2)).clip(lower=0.0)
    bear_gap = (featured["low"].shift(2) - featured["high"]).clip(lower=0.0)
    featured["bull_fvg"] = (bull_gap > 0).astype(int)
    featured["bear_fvg"] = (bear_gap > 0).astype(int)
    featured["bull_fvg_gap_atr"] = bull_gap / atr_base
    featured["bear_fvg_gap_atr"] = bear_gap / atr_base

    structure_bias = np.zeros(len(featured), dtype=int)
    current_bias = 0
    for idx, (up_break, down_break) in enumerate(
        zip(featured["structure_break_up_10"].fillna(0), featured["structure_break_down_10"].fillna(0))
    ):
        if int(up_break) == 1:
            current_bias = 1
        elif int(down_break) == 1:
            current_bias = -1
        structure_bias[idx] = current_bias
    featured["structure_bias_10"] = pd.Series(structure_bias, index=featured.index, dtype=int)

    previous_day_high = _previous_day_levels(featured.index, featured["high"])
    previous_day_low = _previous_day_low(featured.index, featured["low"])
    previous_day_mid = (previous_day_high + previous_day_low) / 2.0

    featured["previous_day_high"] = previous_day_high
    featured["previous_day_low"] = previous_day_low
    featured["previous_day_mid"] = previous_day_mid
    featured["dist_to_previous_day_high_atr"] = (previous_day_high - featured["close"]) / atr_base
    featured["dist_to_previous_day_low_atr"] = (featured["close"] - previous_day_low) / atr_base
    featured["liquidity_sweep_previous_day_high"] = (
        (featured["high"] > previous_day_high) & (featured["close"] <= previous_day_high)
    ).astype(int)
    featured["liquidity_sweep_previous_day_low"] = (
        (featured["low"] < previous_day_low) & (featured["close"] >= previous_day_low)
    ).astype(int)
    featured["close_above_previous_day_mid"] = (featured["close"] > previous_day_mid).astype(int)

    return featured
