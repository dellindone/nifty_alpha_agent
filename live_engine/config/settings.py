"""
Central settings — all standalone variables belong here.
Import the class you need; never hardcode values inline.

    from config.settings import BTC, Equity, Risk, Paths, Model

Secrets live in .env and are loaded via os.getenv().
"""

import os
from dataclasses import dataclass
from pathlib import Path

import pytz

# ── Shared ────────────────────────────────────────────────────────────────────

IST = pytz.timezone("Asia/Kolkata")


# ── Paths ─────────────────────────────────────────────────────────────────────

class Paths:
    ROOT        = Path(__file__).resolve().parents[2]
    DATA        = ROOT / "data"
    MODELS      = ROOT / "models"
    LOGS        = ROOT / "logs"
    EXPERIMENTS = ROOT / "experiments"
    PIPELINES   = ROOT / "pipelines"

    DATA_DIRS = {
        "btc":       DATA / "btc",
        "nifty":     DATA / "nifty",
        "sensex":    DATA / "sensex",
        "banknifty": DATA / "banknifty",
    }

    PROD = MODELS / "prod"

    MODEL_DIRS = {
        "btc":       MODELS / "btc",
        "nifty":     PROD / "nifty_alpha_agent_model",
        "banknifty": PROD / "banknifty_alpha_agent_model",
        "sensex":    PROD / "sensex_alpha_agent_model",
    }


# ── BTC ───────────────────────────────────────────────────────────────────────

class BTC:
    # ── Delta Exchange ────────────────────────────────────────────────────────
    API_KEY    = os.getenv("DELTA_API_KEY", "")
    API_SECRET = os.getenv("DELTA_API_SECRET", "")
    BASE_URL   = os.getenv("DELTA_BASE_URL", "https://api.delta.exchange")
    WS_URL     = "wss://socket.delta.exchange"
    SYMBOL                 = "BTCUSDT"
    CANDLE_FALLBACK_SYMBOL = "BTCUSD"

    # ── Binance (data source) ─────────────────────────────────────────────────
    BINANCE_SYMBOL    = "BTCUSDT"
    BINANCE_BASE_URLS = [
        "https://api.binance.com",
        "https://api1.binance.com",
        "https://api2.binance.com",
        "https://api3.binance.com",
    ]

    # ── Fees & FX ─────────────────────────────────────────────────────────────
    TAKER_FEE_RATE = 0.0005
    MAKER_FEE_RATE = 0.0002
    USD_TO_INR     = float(os.getenv("BTC_USD_INR", "84.0"))
    INR_TO_USD     = 1.0 / float(os.getenv("BTC_USD_INR", "84.0"))
    ENTRY_FEE_MODE = os.getenv("BTC_ENTRY_FEE_MODE", "taker").strip().lower()
    EXIT_FEE_MODE  = os.getenv("BTC_EXIT_FEE_MODE",  "taker").strip().lower()

    # ── Trading parameters ────────────────────────────────────────────────────
    CONTRACT_SIZE     = 0.001   # minimum position increment (BTC)
    MARGIN_PCT        = 0.10
    SL_ATR_MULT       = 1.5
    TP_ATR_MULT       = 3.0
    FORWARD_BARS      = 360     # labeling horizon in primary-TF bars
    COOLDOWN_MINUTES  = 5       # no re-entry after a timeout exit
    TIMEOUT_MINUTES   = 360     # max trade duration
    PARTIAL_EXIT_R    = 1.0     # take partial profit at 1R
    PARTIAL_EXIT_FRACTION = 0.30
    MIN_REGIME_SAMPLES = 500    # min bars to train a regime model

    # ── Timeframes ────────────────────────────────────────────────────────────
    TIMEFRAMES  = ["1m", "15m", "45m", "1h", "1d"]
    PRIMARY_TF  = "45m"


# ── Equity ────────────────────────────────────────────────────────────────────

class Equity:
    # ── Fyers credentials ─────────────────────────────────────────────────────
    FYERS_CLIENT_ID  = os.getenv("FYERS_CLIENT_ID", "")
    FYERS_SECRET_KEY = os.getenv("FYERS_SECRET_KEY", "")

    # ── Market session ────────────────────────────────────────────────────────
    MARKET_OPEN  = "09:15"
    MARKET_CLOSE = "15:30"
    TIMEFRAMES   = [5, 15, 60]      # minutes, matching Fyers resolution codes
    RESOLUTIONS  = ["5", "15", "60", "D"]

    # ── Data download ─────────────────────────────────────────────────────────
    LOOKBACK_DAYS       = 1460       # ~4 years of history
    INTRADAY_CHUNK_DAYS = 90         # Fyers max per intraday request
    DAILY_CHUNK_DAYS    = 365
    TOKEN_MAX_AGE_SECONDS       = 72_000    # re-login after 20 hours
    OPTION_CHAIN_CSV_CACHE_TTL  = 21_600    # 6 hours

    # ── Fees ──────────────────────────────────────────────────────────────────
    GST_RATE         = 0.18
    BROKERAGE_PER_ORDER = 40.0      # flat ₹40 per order
    EXCHANGE_CHARGE  = 10.0
    STT_RATE         = 0.0015       # post Budget 2024
    STAMP_DUTY_RATE  = 0.00003

    # ── Signal thresholds — fallback defaults (use INSTRUMENT_CONFIGS for per-instrument) ──
    MIN_CONFIDENCE     = 0.65
    MIN_RR             = 1.5
    MAX_TRADES_PER_DAY = 3
    DAILY_TARGET       = 6_000
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
    "BANKNIFTY": InstrumentConfig(
        min_confidence=0.55,
        min_rr=1.2,
        max_trades_per_day=3,
        daily_target=12_000,
        abs_sl_max=100,
        atr_mult_scale=0.5,
        trail_width_mult=1.0,
        trail_activation_rr=0.75,
    ),
    "SENSEX": InstrumentConfig(
        min_confidence=0.55,
        min_rr=1.2,
        max_trades_per_day=3,
        daily_target=8_000,
        abs_sl_max=120,
        atr_mult_scale=0.5,
        trail_width_mult=0.5,
        trail_activation_rr=0.75,
    ),
}


def get_instrument_config(instrument: str) -> InstrumentConfig:
    return INSTRUMENT_CONFIGS.get(instrument.upper(), InstrumentConfig(
        min_confidence=Equity.MIN_CONFIDENCE,
        min_rr=Equity.MIN_RR,
        max_trades_per_day=Equity.MAX_TRADES_PER_DAY,
        daily_target=Equity.DAILY_TARGET,
    ))


# ── Risk ──────────────────────────────────────────────────────────────────────

class Risk:
    # ── Capital ───────────────────────────────────────────────────────────────
    INITIAL_CAPITAL_INR  = 500_000
    INITIAL_CAPITAL_USD  = 1_000
    MAX_DRAWDOWN_PCT     = 0.10
    CAPITAL_RESERVE_PCT  = 0.20
    BTC_MAX_DRAWDOWN_PCT = 0.15

    # ── VIX guards (equity) ───────────────────────────────────────────────────
    VIX_NO_NEW_TRADES        = 30.0
    VIX_HIGH_MIN_SL          = 35.0
    VIX_LOW_MAX_SL           = 20.0
    ABS_SL_MIN               = 5.0
    ABS_SL_MAX               = 60.0
    INTRADAY_SPIKE_THRESHOLD = 0.05
    INTRADAY_SPIKE_WIDEN_MULT = 1.5

    # ── ATR-based SL multipliers per bin ──────────────────────────────────────
    ATR_MULTIPLIERS = {"TIGHT": 0.75, "NARROW": 1.0, "MEDIUM": 1.5, "WIDE": 2.0}


# ── Model ─────────────────────────────────────────────────────────────────────

class Model:
    MIN_OOS_WEEKS = 4           # min out-of-sample weeks before promotion
    RETRAIN_DAY   = "Sunday"    # used by pipelines/weekly_retrain.py


# ── Logging & notifications ───────────────────────────────────────────────────

class Logging:
    LEVEL      = os.getenv("LOG_LEVEL", "INFO")
    FILE_NIFTY = Paths.LOGS / "shadow_nifty.log"
    FILE_BTC   = Paths.LOGS / "shadow_btc.log"
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
