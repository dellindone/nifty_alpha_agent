import numpy as np
import pandas as pd

from risk.position_sizer import stop_loss_from_bin


def _bucket_ratio(value: pd.Series) -> pd.Series:
    bins = [-np.inf, 0.35, 0.75, 1.25, np.inf]
    labels = ["TIGHT", "MEDIUM", "WIDE", "VERY_WIDE"]
    # Persist as concrete strings instead of categorical codes to keep
    # downstream interfaces stable across parquet/CSV round-trips.
    return pd.cut(value, bins=bins, labels=labels).astype("string")


def _bucket_sl_ratio(value: pd.Series) -> pd.Series:
    # 5-class sl_bin aligned to live ATR_MULTIPLIERS (TIGHT=0.75, NARROW=1.0,
    # MEDIUM=1.5, WIDE=2.0, VERY_WIDE=2.5). Each bin means "adverse excursion
    # needed at least this SL multiplier to survive."
    bins   = [-np.inf, 0.75, 1.0, 1.5, 2.0, np.inf]
    labels = ["TIGHT", "NARROW", "MEDIUM", "WIDE", "VERY_WIDE"]
    return pd.cut(value, bins=bins, labels=labels).astype("string")


def _phase1_multiplier(favorable_ratio: pd.Series) -> pd.Series:
    conditions = [
        favorable_ratio <= 0.75,
        favorable_ratio <= 1.25,
        favorable_ratio <= 1.75,
    ]
    choices = [0.5, 1.0, 1.5]
    return pd.Series(np.select(conditions, choices, default=2.0), index=favorable_ratio.index)


def _select_trail_tf(favorable_ratio: pd.Series) -> pd.Series:
    conditions = [
        favorable_ratio <= 0.75,
        favorable_ratio <= 1.5,
    ]
    choices = ["5m", "15m"]
    return pd.Series(np.select(conditions, choices, default="60m"), index=favorable_ratio.index)


def _forward_window_max(series: pd.Series, horizon: int) -> pd.Series:
    return series[::-1].rolling(horizon, min_periods=horizon).max()[::-1].shift(-1)


def _forward_window_min(series: pd.Series, horizon: int) -> pd.Series:
    return series[::-1].rolling(horizon, min_periods=horizon).min()[::-1].shift(-1)


def build_labels(feature_df: pd.DataFrame, horizon: int = 3) -> pd.DataFrame:
    """
    Canonical label builder for the project.

    Output columns:
    - direction (Int64): 1 bullish, 0 bearish
    - adverse_excursion (float)
    - favorable_excursion (float)
    - sl_bin (string): TIGHT/MEDIUM/WIDE/VERY_WIDE
    - trail_bin (string): TIGHT/MEDIUM/WIDE/VERY_WIDE
    - phase1_target (float)
    - trail_tf (string): 5m/15m/60m
    """
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    if "atr_14" not in feature_df.columns:
        raise ValueError("df must contain atr_14. Call compute_pattern_context first.")

    future_close = feature_df["close"].shift(-horizon)
    future_high_max = _forward_window_max(feature_df["high"], horizon)
    future_low_min = _forward_window_min(feature_df["low"], horizon)

    direction = (future_close > feature_df["close"]).astype("Int64")

    bullish_adverse = (feature_df["close"] - future_low_min).clip(lower=0.0)
    bearish_adverse = (future_high_max - feature_df["close"]).clip(lower=0.0)
    adverse_excursion = np.where(direction.fillna(0).astype(int) == 1, bullish_adverse, bearish_adverse)

    bullish_favorable = (future_high_max - feature_df["close"]).clip(lower=0.0)
    bearish_favorable = (feature_df["close"] - future_low_min).clip(lower=0.0)
    favorable_excursion = np.where(direction.fillna(0).astype(int) == 1, bullish_favorable, bearish_favorable)

    atr_base = feature_df["atr_14"].replace(0.0, np.nan)
    adverse_ratio = pd.Series(adverse_excursion, index=feature_df.index) / atr_base
    favorable_ratio = pd.Series(favorable_excursion, index=feature_df.index) / atr_base

    phase1_multiplier = _phase1_multiplier(favorable_ratio)

    labels = pd.DataFrame(index=feature_df.index)
    labels["direction"] = direction
    labels["adverse_excursion"] = pd.Series(adverse_excursion, index=feature_df.index)
    labels["favorable_excursion"] = pd.Series(favorable_excursion, index=feature_df.index)
    labels["sl_bin"] = _bucket_sl_ratio(adverse_ratio)
    labels["trail_bin"] = _bucket_ratio(favorable_ratio)
    labels["phase1_target"] = phase1_multiplier * feature_df["atr_14"]
    labels["trail_tf"] = _select_trail_tf(favorable_ratio)

    return labels.iloc[:-horizon].copy()


def _scan_session_barriers(
    highs: np.ndarray, lows: np.ndarray, i: int,
    ce_sl: float, ce_tp: float, pe_sl: float, pe_tp: float,
) -> tuple[str | None, int | None]:
    """Scan forward bars to find which barrier (CE or PE) is touched first.
    Returns (selected_side, hit_index) where side is 'CE', 'PE', or None."""
    ce_result = ce_hit = pe_result = pe_hit = None
    for j in range(i + 1, len(highs)):
        if ce_result is None:
            if lows[j]  <= ce_sl: ce_result, ce_hit = "SL_HIT", j
            elif highs[j] >= ce_tp: ce_result, ce_hit = "TP_HIT", j
        if pe_result is None:
            if highs[j] >= pe_sl: pe_result, pe_hit = "SL_HIT", j
            elif lows[j]  <= pe_tp: pe_result, pe_hit = "TP_HIT", j
        if ce_result and pe_result:
            break

    if ce_result == "TP_HIT" and pe_result != "TP_HIT":
        return "CE", ce_hit
    if pe_result == "TP_HIT" and ce_result != "TP_HIT":
        return "PE", pe_hit
    if ce_result == "TP_HIT" and pe_result == "TP_HIT":
        if ce_hit is not None and pe_hit is not None:
            return ("CE", ce_hit) if ce_hit <= pe_hit else ("PE", pe_hit)
    return None, None


def build_barrier_labels(
    feature_df: pd.DataFrame,
    min_rr: float = 2.0,
    sl_bin_reference: str = "TIGHT",
) -> pd.DataFrame:
    """
    Session-aware label builder that uses first-touch barrier logic.

    Output columns:
    - trade_class (string): CE_TP_FIRST / PE_TP_FIRST / NO_TRADE
    - direction (Int64): 1 bullish, 0 bearish, <NA> for NO_TRADE
    - adverse_excursion (float)
    - favorable_excursion (float)
    - sl_bin (string)
    - trail_bin (string)
    - phase1_target (float)
    - trail_tf (string)
    """
    if "atr_14" not in feature_df.columns:
        raise ValueError("df must contain atr_14. Call compute_pattern_context first.")
    if not isinstance(feature_df.index, pd.DatetimeIndex):
        raise ValueError("feature_df index must be a DatetimeIndex")

    if feature_df.index.tz is None:
        local_index = feature_df.index.tz_localize("Asia/Kolkata")
    else:
        local_index = feature_df.index.tz_convert("Asia/Kolkata")

    session_dates = pd.Series(local_index.date, index=feature_df.index)
    trade_class = pd.Series("NO_TRADE", index=feature_df.index, dtype="string")
    direction = pd.Series(pd.NA, index=feature_df.index, dtype="Int64")
    adverse_excursion = pd.Series(np.nan, index=feature_df.index, dtype=float)
    favorable_excursion = pd.Series(np.nan, index=feature_df.index, dtype=float)

    for _, session_frame in feature_df.groupby(session_dates):
        if len(session_frame) < 2:
            continue

        session_highs = session_frame["high"].to_numpy(dtype=float)
        session_lows = session_frame["low"].to_numpy(dtype=float)
        session_closes = session_frame["close"].to_numpy(dtype=float)
        session_atr = session_frame["atr_14"].to_numpy(dtype=float)
        if "vix" in session_frame.columns:
            session_vix = pd.to_numeric(session_frame["vix"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        else:
            session_vix = np.zeros(len(session_frame), dtype=float)
        session_index = session_frame.index

        for i in range(len(session_frame) - 1):
            entry_close = float(session_closes[i])
            atr_value   = float(session_atr[i])
            vix_value   = float(session_vix[i])
            if not np.isfinite(entry_close) or not np.isfinite(atr_value) or atr_value <= 0:
                continue

            sl_points = float(stop_loss_from_bin(sl_bin_reference, atr_value, vix_value))
            if sl_points <= 0:
                continue

            selected_side, _ = _scan_session_barriers(
                session_highs, session_lows, i,
                ce_sl=entry_close - sl_points,
                ce_tp=entry_close + sl_points * min_rr,
                pe_sl=entry_close + sl_points,
                pe_tp=entry_close - sl_points * min_rr,
            )
            if selected_side is None:
                continue

            future_slice_high = session_highs[i + 1 :]
            future_slice_low = session_lows[i + 1 :]
            if selected_side == "CE":
                trade_class.loc[session_index[i]] = "CE_TP_FIRST"
                direction.loc[session_index[i]] = 1
                favorable_excursion.loc[session_index[i]] = float(np.nanmax(future_slice_high) - entry_close)
                adverse_excursion.loc[session_index[i]] = float(entry_close - np.nanmin(future_slice_low))
            else:
                trade_class.loc[session_index[i]] = "PE_TP_FIRST"
                direction.loc[session_index[i]] = 0
                favorable_excursion.loc[session_index[i]] = float(entry_close - np.nanmin(future_slice_low))
                adverse_excursion.loc[session_index[i]] = float(np.nanmax(future_slice_high) - entry_close)

    atr_base = feature_df["atr_14"].replace(0.0, np.nan)
    adverse_ratio = adverse_excursion / atr_base
    favorable_ratio = favorable_excursion / atr_base
    phase1_multiplier = _phase1_multiplier(favorable_ratio)

    labels = pd.DataFrame(index=feature_df.index)
    labels["trade_class"] = trade_class
    labels["direction"] = direction
    labels["adverse_excursion"] = adverse_excursion
    labels["favorable_excursion"] = favorable_excursion
    labels["sl_bin"] = _bucket_sl_ratio(adverse_ratio)
    labels["trail_bin"] = _bucket_ratio(favorable_ratio)
    action_mask = direction.notna()
    labels["phase1_target"] = (phase1_multiplier * feature_df["atr_14"]).where(action_mask)
    labels["trail_tf"] = _select_trail_tf(favorable_ratio).where(action_mask)
    return labels.copy()
