from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

import pandas as pd

from config.instruments import FYERS_SYMBOL
from config.settings import IST
from ingestion.fyers_client import fyers_client

logger = logging.getLogger(__name__)
_FRAME_TTL = {"5": timedelta(minutes=5), "15": timedelta(minutes=15), "60": timedelta(minutes=60), "D": timedelta(hours=12), "VIX": timedelta(minutes=10)}
_CACHE: dict[tuple[str, str], tuple[pd.DataFrame, datetime]] = {}
_LOCK = threading.Lock()


def _cached(symbol: str, resolution: str, fetch_fn) -> pd.DataFrame | None:
    key, now, ttl = (symbol, resolution), datetime.now(IST), _FRAME_TTL.get(resolution, timedelta(minutes=5))
    cached = _CACHE.get(key)
    if cached is not None and (now - cached[1]) <= ttl:
        return cached[0]
    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None and (now - cached[1]) <= ttl:
            return cached[0]
        fetched = fetch_fn(symbol, resolution)
        if not fetched.empty:
            _CACHE[key] = (fetched, now)
            return fetched
        return cached[0] if cached is not None else None


def fetch_live_frames(engine, now_ist: datetime) -> dict[str, pd.DataFrame]:
    def _fetch(symbol: str, resolution: str, bars: int, days_back: int) -> pd.DataFrame:
        try:
            end_date = datetime.now(IST).date(); start_date = end_date - timedelta(days=days_back)
            candles = fyers_client.get_historical(symbol=symbol, resolution=resolution, date_from=start_date.strftime("%Y-%m-%d"), date_to=end_date.strftime("%Y-%m-%d"))
            df = pd.DataFrame(candles or [], columns=["timestamp", "open", "high", "low", "close", "volume"])
            if df.empty: logger.error("candle_poll failed instrument=%s error=empty", symbol); return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True); df = df.set_index("timestamp").sort_index().tail(bars).copy()
            logger.info("candle_poll ok instrument=%s bars=%d", symbol, len(df)); return df
        except Exception as exc:
            engine.health.update("fyers_candle_api", "critical", str(exc)); logger.error("candle_poll failed instrument=%s error=%s", symbol, exc); return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    sym = FYERS_SYMBOL[engine.instrument]
    frame_5m = _cached(sym, "5", lambda s, r: _fetch(s, r, 300, 30)); frame_15m = _cached(sym, "15", lambda s, r: _fetch(s, r, 300, 60)); frame_60m = _cached(sym, "60", lambda s, r: _fetch(s, r, 300, 99)); frame_D = _cached(sym, "D", lambda s, r: _fetch(s, r, 600, 900))
    missing = [r for r, f in [("5m", frame_5m), ("60m", frame_60m), ("D", frame_D)] if f is None]
    if missing:
        engine.health.update("fyers_candle_api", "critical", ",".join(missing)); engine._last_decision = f"NO_SIGNAL (FRAMES_UNAVAILABLE:{','.join(missing)})"; engine._log_poll(now_ist, "SKIP"); engine._print_live_display(now_ist); return {}
    engine.health.update("fyers_candle_api", "ok", "")
    vix_5m = _cached("NSE:INDIAVIX-INDEX", "VIX", lambda s, r: _fetch("NSE:INDIAVIX-INDEX", "5", 400, 30))
    if vix_5m is None:
        engine.health.update("fyers_vix", "warn", "unavailable"); engine._last_decision = "NO_SIGNAL (VIX_UNAVAILABLE)"; engine._log_poll(now_ist, "SKIP"); engine._print_live_display(now_ist); return {}
    engine.health.update("fyers_vix", "ok", "")
    if "close" in vix_5m.columns:
        left = frame_5m.sort_index().reset_index().rename(columns={"index": "timestamp"}); right = vix_5m[["close"]].rename(columns={"close": "vix"}).sort_index().reset_index().rename(columns={"index": "timestamp"})
        frame_5m = pd.merge_asof(left, right, on="timestamp", direction="backward").set_index("timestamp").sort_index()
    return {"5": frame_5m, "15": frame_15m, "60": frame_60m, "D": frame_D, "5m": frame_5m, "15m": frame_15m, "60m": frame_60m}
