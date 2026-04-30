import os
from dataclasses import dataclass
from pathlib import Path

import pytz

IST = pytz.timezone("Asia/Kolkata")


class Paths:
    ROOT = Path(__file__).resolve().parents[2]
    DATA = ROOT / "data"
    MODELS = ROOT / "models"
    LOGS = ROOT / "logs"

    DATA_DIRS = {
        "nifty": DATA / "nifty",
    }

    MODEL_DIRS = {
        "nifty": MODELS,
    }


class Equity:
    FYERS_CLIENT_ID = os.getenv("FYERS_CLIENT_ID", "")
    FYERS_SECRET_KEY = os.getenv("FYERS_SECRET_KEY", "")
    MARKET_OPEN = "09:15"
    MARKET_CLOSE = "15:30"
    TIMEFRAMES = [5, 15, 60]
    RESOLUTIONS = ["5", "15", "60", "D"]
    LOOKBACK_DAYS = 1460
    INTRADAY_CHUNK_DAYS = 90
    DAILY_CHUNK_DAYS = 365
    TOKEN_MAX_AGE_SECONDS = 72_000
    OPTION_CHAIN_CSV_CACHE_TTL = 21_600
    GST_RATE = 0.18
    BROKERAGE_PER_ORDER = 40.0
    EXCHANGE_CHARGE = 10.0
    STT_RATE = 0.0015
    STAMP_DUTY_RATE = 0.00003
    MIN_CONFIDENCE = 0.65
    MIN_RR = 1.5
    MAX_TRADES_PER_DAY = 3
    DAILY_TARGET = 6_000
    SPREAD_THRESHOLD_PCT = 2.0


@dataclass(frozen=True)
class InstrumentConfig:
    min_confidence: float
    min_rr: float
    max_trades_per_day: int
    daily_target: int
    spread_threshold_pct: float = 2.0
    abs_sl_min: float = 5.0
    abs_sl_max: float = 60.0
    atr_mult_scale: float = 1.0
    trail_width_mult: float = 1.0
    trail_activation_rr: float = 1.0


INSTRUMENT_CONFIGS: dict[str, InstrumentConfig] = {
    "NIFTY": InstrumentConfig(
        min_confidence=0.55,
        min_rr=1.2,
        max_trades_per_day=6,
        daily_target=6_000,
        abs_sl_max=9999,
        atr_mult_scale=1.25,
        trail_width_mult=0.5,
        trail_activation_rr=1.0,
    ),
}


def get_instrument_config(instrument: str) -> InstrumentConfig:
    return INSTRUMENT_CONFIGS.get(instrument.upper(), InstrumentConfig(
        min_confidence=Equity.MIN_CONFIDENCE,
        min_rr=Equity.MIN_RR,
        max_trades_per_day=Equity.MAX_TRADES_PER_DAY,
        daily_target=Equity.DAILY_TARGET,
    ))


class Risk:
    INITIAL_CAPITAL_INR = 500_000
    INITIAL_CAPITAL_USD = 1_000
    MAX_DRAWDOWN_PCT = 0.10
    CAPITAL_RESERVE_PCT = 0.20
    BTC_MAX_DRAWDOWN_PCT = 0.15
    VIX_NO_NEW_TRADES = 30.0
    VIX_HIGH_MIN_SL = 35.0
    VIX_LOW_MAX_SL = 20.0
    ABS_SL_MIN = 5.0
    ABS_SL_MAX = 60.0
    INTRADAY_SPIKE_THRESHOLD = 0.05
    INTRADAY_SPIKE_WIDEN_MULT = 1.5
    ATR_MULTIPLIERS = {"TIGHT": 0.75, "NARROW": 1.0, "MEDIUM": 1.5, "WIDE": 2.0}


class Logging:
    LEVEL = os.getenv("LOG_LEVEL", "INFO")
    FILE_NIFTY = Paths.LOGS / "shadow_nifty.log"
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
