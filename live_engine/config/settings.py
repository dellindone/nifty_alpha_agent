import os
from dataclasses import dataclass
from pathlib import Path

import pytz
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

IST = pytz.timezone("Asia/Kolkata")


class Paths:
    ROOT          = Path(__file__).resolve().parents[2]
    DATA          = ROOT / "data"
    MODELS        = ROOT / "models"
    MODELS_LIVE   = ROOT / "models" / "live"
    LOGS          = ROOT / "logs"

    DATA_DIRS = {
        "nifty": DATA / "nifty",
    }


class Equity:
    # ── Market session ────────────────────────────────────────────────────────
    MARKET_CLOSE = "15:30"

    # ── Fyers API ─────────────────────────────────────────────────────────────
    TOKEN_MAX_AGE_SECONDS      = 72_000   # re-login after 20 hours
    OPTION_CHAIN_CSV_CACHE_TTL = 21_600   # 6 hours

    # ── Fees ──────────────────────────────────────────────────────────────────
    GST_RATE            = 0.18
    BROKERAGE_PER_ORDER = 40.0            # flat ₹40 per order
    EXCHANGE_CHARGE     = 10.0
    STT_RATE            = 0.0015          # post Budget 2024
    STAMP_DUTY_RATE     = 0.00003

    # ── Fallback signal thresholds (use INSTRUMENT_CONFIGS for per-instrument) ──
    MIN_CONFIDENCE     = 0.55
    MIN_RR             = 1.2
    MAX_TRADES_PER_DAY = 5
    DAILY_TARGET       = 5_000
    SPREAD_THRESHOLD_PCT = 2.0

@dataclass(frozen=True)
class InstrumentConfig:
    min_confidence: float
    min_rr: float
    max_trades_per_day: int
    daily_target: int
    daily_loss_limit: int       # stop all new trades when realized loss >= this (positive number)
    max_lots: int               # maximum lots per trade; scales down toward 1 as daily target approaches
    spread_threshold_pct: float = 2.0
    abs_sl_min: float = 5.0
    abs_sl_max: float = 60.0
    atr_mult_scale: float = 1.0
    trail_width_mult: float = 1.0
    trail_activation_rr: float = 1.0
    min_session_bar: int = 6  # block signals before this bar (bar 6 = 09:45 close, lets OR settle)


INSTRUMENT_CONFIGS: dict[str, InstrumentConfig] = {
    "NIFTY": InstrumentConfig(
        min_confidence=0.60,
        min_rr=1.2,
        max_trades_per_day=5,
        daily_target=5_000,
        daily_loss_limit=3_000,
        max_lots=1,
        abs_sl_max=9999,
        atr_mult_scale=1.25,
        trail_width_mult=0.5,
        trail_activation_rr=1.0,
        min_session_bar=0,
    ),
}


def get_instrument_config(instrument: str) -> InstrumentConfig:
    return INSTRUMENT_CONFIGS.get(instrument.upper(), InstrumentConfig(
        min_confidence=Equity.MIN_CONFIDENCE,
        min_rr=Equity.MIN_RR,
        max_trades_per_day=Equity.MAX_TRADES_PER_DAY,
        daily_target=Equity.DAILY_TARGET,
        daily_loss_limit=Equity.DAILY_TARGET,
        max_lots=1,
    ))


class Risk:
    # ── VIX guards ────────────────────────────────────────────────────────────
    VIX_NO_NEW_TRADES         = 30.0
    VIX_HIGH_MIN_SL           = 35.0
    VIX_LOW_MAX_SL            = 20.0
    ABS_SL_MIN                = 5.0
    ABS_SL_MAX                = 60.0
    INTRADAY_SPIKE_THRESHOLD  = 0.05
    INTRADAY_SPIKE_WIDEN_MULT = 1.5

    # ── ATR-based SL multipliers per bin ──────────────────────────────────────
    ATR_MULTIPLIERS = {"TIGHT": 0.75, "NARROW": 1.0, "MEDIUM": 1.5, "WIDE": 2.0, "VERY_WIDE": 2.5}


class Logging:
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")


class Trading:
    BROKER_NAME     = os.getenv("BROKER_NAME", "fyers")
    ACCOUNT_NAME    = os.getenv("ACCOUNT_NAME", "")
    INITIAL_CAPITAL = float(os.getenv("INITIAL_CAPITAL", "21000"))
