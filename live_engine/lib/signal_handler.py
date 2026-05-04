"""Signal conversion layer from model predictions to executable shadow trades."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd


from config.instruments import LOT_SIZES
from ingestion.option_chain import option_chain_service
from model.predict import ModelPrediction
from risk.position_sizer import stop_loss_from_bin
from strategy.strike_selector import strike_selector
from config.settings import Equity, get_instrument_config

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    instrument: str
    direction: int
    option_type: str
    strike: int
    expiry_date: date
    entry_premium: float
    sl_price: float
    target_price: float
    trail_bin: str
    trail_tf: str
    confidence: float
    direction_prob: float
    vix: float
    atr: float
    lot_size: int
    lots: int = 1
    blocked: bool = False
    block_reason: str = ""


def lots_for_day(daily_pnl: float, daily_target: float, max_lots: int = 3) -> int:
    remaining = daily_target - daily_pnl
    if remaining <= 0:
        return 0
    if remaining < daily_target * 0.33:
        tier = 1
    elif remaining < daily_target * 0.67:
        tier = 2
    else:
        tier = 3
    return min(tier, max_lots)


class SignalHandler:
    def __init__(self) -> None:
        self.last_block_reason: str = ""

    def process(
        self,
        prediction: ModelPrediction,
        feature_row: pd.DataFrame,
        instrument: str,
        daily_pnl: float = 0.0,
        daily_trade_count: int = 0,
    ) -> TradeSignal | None:
        instrument_key = instrument.upper()
        cfg = get_instrument_config(instrument_key)
        if len(feature_row) != 1:
            raise ValueError("feature_row must be a single-row DataFrame")

        row = feature_row.iloc[-1]

        def _block(reason: str) -> None:
            logger.info("NO_SIGNAL reason=%s", reason)
            self.last_block_reason = reason

        if not prediction.should_trade or prediction.trade_class == "NO_TRADE":
            _block("MODEL_NO_TRADE")
            return None
        session_bar = int(row.get("session_bar", 999))
        if session_bar < cfg.min_session_bar:
            _block(f"TOO_EARLY bar={session_bar} min={cfg.min_session_bar}")
            return None
        if float(prediction.confidence) < cfg.min_confidence:
            _block(f"LOW_CONF {float(prediction.confidence):.0%} < {cfg.min_confidence:.0%}")
            return None
        if float(daily_pnl) <= -abs(cfg.daily_loss_limit):
            _block(f"DAILY_LOSS_LIMIT pnl=₹{daily_pnl:.0f} limit=₹{cfg.daily_loss_limit}")
            return None
        max_trades_hit = int(daily_trade_count) >= cfg.max_trades_per_day
        lots = lots_for_day(float(daily_pnl), cfg.daily_target, max_lots=cfg.max_lots)
        if not max_trades_hit and lots <= 0:
            _block(f"DAILY_TARGET_HIT pnl=₹{daily_pnl:.0f}")
            return None

        vix = float(row.get("vix", 0.0))
        atr = float(row.get("atr_14", 0.0))
        if atr <= 0:
            _block("ZERO_ATR")
            return None

        lot_size = LOT_SIZES.get(instrument_key)
        if lot_size is None or lot_size <= 0:
            _block(f"NO_LOT_SIZE({instrument_key})")
            return None

        sl_price = float(stop_loss_from_bin(prediction.sl_bin, atr, vix, cfg=cfg))
        target_price = float(prediction.phase1_target)
        if target_price <= 0 or sl_price <= 0:
            _block(f"ZERO_SL_OR_TARGET sl={sl_price:.2f} tp={target_price:.2f}")
            return None

        rr = target_price / sl_price
        if rr < cfg.min_rr:
            _block(f"LOW_RR {rr:.2f} < {cfg.min_rr} (sl={sl_price:.2f} tp={target_price:.2f})")
            return None

        direction_label = "BULLISH" if prediction.direction == 1 else "BEARISH"
        option_type = "CE" if prediction.direction == 1 else "PE"
        direction = 1 if option_type == "CE" else 0
        side_prob = float(
            prediction.direction_prob if prediction.direction == 1 else (1.0 - prediction.direction_prob)
        )

        chain = option_chain_service.get_best_instrument(instrument_key, direction_label)
        if not chain or not chain.get("processed"):
            _block(f"NO_OPTION_CHAIN({direction_label})")
            return None
        selected = strike_selector.select(
            chain["processed"],
            chain.get("atm", float(row.get("close", 0.0))),
            direction_label,
            instrument=instrument_key,
        )
        if not selected:
            _block(f"NO_STRIKE({direction_label})")
            return None

        entry_premium = float(selected.get("lp", 0.0))
        strike = int(float(selected.get("strike", 0.0)))
        expiry = chain.get("expiry")
        if entry_premium <= 0 or strike <= 0 or expiry is None:
            _block(f"INVALID_OPTION entry={entry_premium:.2f} strike={strike} expiry={expiry}")
            return None

        if max_trades_hit:
            block_reason = f"MAX_TRADES({daily_trade_count})"
            _block(block_reason)
            return TradeSignal(
                instrument=instrument_key,
                direction=direction,
                option_type=option_type,
                strike=strike,
                expiry_date=expiry,
                entry_premium=entry_premium,
                sl_price=sl_price,
                target_price=target_price,
                trail_bin=str(prediction.trail_bin),
                trail_tf=str(prediction.trail_tf),
                confidence=float(prediction.confidence),
                direction_prob=side_prob,
                vix=vix,
                atr=atr,
                lot_size=int(lot_size),
                lots=int(lots),
                blocked=True,
                block_reason=block_reason,
            )

        return TradeSignal(
            instrument=instrument_key,
            direction=direction,
            option_type=option_type,
            strike=strike,
            expiry_date=expiry,
            entry_premium=entry_premium,
            sl_price=sl_price,
            target_price=target_price,
            trail_bin=str(prediction.trail_bin),
            trail_tf=str(prediction.trail_tf),
            confidence=float(prediction.confidence),
            direction_prob=side_prob,
            vix=vix,
            atr=atr,
            lot_size=int(lot_size),
            lots=int(lots),
        )
