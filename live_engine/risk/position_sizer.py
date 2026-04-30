"""Position sizing and SL conversion rules for shadow/live readiness."""

from __future__ import annotations

import logging
import math
from config.settings import Risk

logger = logging.getLogger(__name__)

def should_block_new_trades(vix: float) -> bool:
    return float(vix) > Risk.VIX_NO_NEW_TRADES


def _clamp_sl(value: float) -> float:
    return max(Risk.ABS_SL_MIN, min(Risk.ABS_SL_MAX, float(value)))


def stop_loss_from_bin(sl_bin: str, atr_14: float, vix: float, cfg=None) -> float:
    atr_base = max(0.0, float(atr_14))
    base_mult = Risk.ATR_MULTIPLIERS.get(str(sl_bin).upper(), Risk.ATR_MULTIPLIERS["MEDIUM"])
    scale = cfg.atr_mult_scale if cfg is not None else 1.0
    sl_rupees = atr_base * base_mult * scale
    if vix > 25:
        sl_rupees = max(sl_rupees, Risk.VIX_HIGH_MIN_SL)
    if vix < 12:
        sl_rupees = min(sl_rupees, Risk.VIX_LOW_MAX_SL)
    sl_min = cfg.abs_sl_min if cfg is not None else Risk.ABS_SL_MIN
    sl_max = cfg.abs_sl_max if cfg is not None else Risk.ABS_SL_MAX
    return max(sl_min, min(sl_max, sl_rupees))


def widened_stop_loss(current_sl_points: float, vix_pct_change_1: float) -> float:
    if float(vix_pct_change_1) > Risk.INTRADAY_SPIKE_THRESHOLD:
        return _clamp_sl(float(current_sl_points) * Risk.INTRADAY_SPIKE_WIDEN_MULT)
    return _clamp_sl(current_sl_points)


class PositionSizer:
    """Phase-aware lot sizing.

    Phase 1 (shadow): always 1 lot.
    Phase 2 (future live): risk-based sizing, capped to 2% risk per trade.
    """

    def __init__(self, shadow_mode: bool = True) -> None:
        self.shadow_mode = bool(shadow_mode)

    def get_lots(self, capital: float, sl_per_unit: float, lot_size: int, vix: float) -> int:
        if self.shadow_mode:
            return 1

        sl = max(float(sl_per_unit), 1e-9)
        lot = max(int(lot_size), 1)
        risk_budget = max(float(capital), 0.0) * 0.02
        lots = math.floor(risk_budget / (sl * lot))
        lots = max(1, min(int(lots), 5))
        return lots

    def get_margin_required(self, premium: float, lot_size: int, lots: int) -> float:
        return float(premium) * int(lot_size) * int(lots) * 1.10


position_sizer = PositionSizer()
