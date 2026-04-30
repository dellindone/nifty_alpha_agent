import gc
import logging
import time
from datetime import date, datetime
from io import StringIO

import pandas as pd
import requests

from config.instruments import (
    LOT_SIZES,
    FYERS_SYMBOL,
    HAS_WEEKLY_EXPIRY,
    MCX_SYMBOLS,
    BSE_INDEX_SYMBOLS,
)
from ingestion.fyers_client import fyers_client
from config.settings import Equity

logger = logging.getLogger(__name__)

NSE_FO_CSV_URL = "https://public.fyers.in/sym_details/NSE_FO.csv"
BSE_FO_CSV_URL = "https://public.fyers.in/sym_details/BSE_FO.csv"
MCX_FO_CSV_URL = "https://public.fyers.in/sym_details/MCX_FO.csv"

class OptionChainService:
    _csv_cache: dict = {}

    def _get_csv_url(self, scrip: str) -> str:
        s = scrip.upper()
        if s in MCX_SYMBOLS:
            return MCX_FO_CSV_URL
        if s in BSE_INDEX_SYMBOLS:
            return BSE_FO_CSV_URL
        return NSE_FO_CSV_URL

    def _fetch_csv(self, scrip: str) -> pd.DataFrame | None:
        scrip_key = scrip.strip().upper()
        try:
            cached = self._csv_cache.get(scrip_key)
            if cached:
                expires_at, cached_df = cached
                if expires_at > time.time():
                    return cached_df.copy()
                self._csv_cache.pop(scrip_key, None)

            url = self._get_csv_url(scrip_key)
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            content = resp.content.decode("utf-8", errors="ignore")
            df = pd.read_csv(StringIO(content), header=None, names=range(21), dtype=object)
            df = df[df[1].str.split().str[0] == scrip_key]
            if df.empty:
                return None

            self._csv_cache[scrip_key] = (time.time() + Equity.OPTION_CHAIN_CSV_CACHE_TTL, df.copy())
            return df
        except Exception as e:
            logger.error(f"CSV fetch failed for {scrip}: {e}")
            return None

    def _filter_scrip(self, df: pd.DataFrame, scrip: str) -> pd.DataFrame | None:
        scrip = scrip.strip().upper()
        df = df[df[1].str.split().str[0] == scrip]
        if df.empty:
            return None
        return df

    def _extract_expiry_dates(self, df: pd.DataFrame) -> pd.DataFrame | None:
        def extract_date(v):
            parts = str(v).split()
            if len(parts) < 4:
                return pd.NaT
            try:
                return datetime.strptime(" ".join(parts[1:4]), "%d %b %y")
            except ValueError:
                return pd.NaT

        try:
            df["date"] = df[1].apply(extract_date)
            return df.dropna(subset=["date"])
        except Exception as e:
            logger.error(f"Date extraction error: {e}")
            return None

    def _select_expiry(self, scrip: str, df: pd.DataFrame) -> tuple:
        try:
            expiry_dates = sorted(df["date"].dt.date.unique())
            today = date.today()
            is_weekly = HAS_WEEKLY_EXPIRY.get(scrip.upper(), False)
            if is_weekly:
                for expiry_date in expiry_dates:
                    delta = (expiry_date - today).days
                    if delta > 0:
                        return expiry_date, delta
            else:
                for expiry_date in expiry_dates:
                    delta = (expiry_date - today).days
                    if delta > 3:
                        return expiry_date, delta
            return None, None
        except Exception as e:
            logger.error(f"Expiry selection error: {e}")
            return None, None

    def _build_strike_chain(self, df: pd.DataFrame, scrip: str, direction: str) -> tuple:
        try:
            option_type = "CE" if direction == "BULLISH" else "PE"
            df = df[df[1].str.endswith(option_type)].copy()
            df["strike"] = df[1].str.split().str[4].astype(float)
            strikes = sorted(df["strike"].unique())
            if len(strikes) < 2:
                return None, None, None

            diff = min(b - a for a, b in zip(strikes, strikes[1:]))
            session = fyers_client.get_session()
            if not session:
                return None, None, None

            ltp = self._fetch_ltp(scrip, session)
            if not ltp:
                return None, None, None

            atm = round(ltp / diff) * diff
            chain = [atm - i * diff for i in range(3, 0, -1)] + [atm] + [atm + i * diff for i in range(1, 6)]
            return df[df["strike"].isin(chain)].copy(), atm, ltp
        except Exception as e:
            logger.error(f"Strike chain build error: {e}")
            return None, None, None

    def _is_auth_error(self, response: dict) -> bool:
        code = response.get("code", 0)
        message = str(response.get("message", "")).lower()
        return response.get("s") == "error" and (
            code in (-16, -14, 10, 16) or "token" in message or "auth" in message or "session" in message
        )

    def _fetch_ltp(self, scrip: str, session) -> float | None:
        try:
            normalized = self._normalize_symbol(scrip)
            data = session.quotes({"symbols": normalized})
            if self._is_auth_error(data):
                fyers_client.invalidate()
                session = fyers_client.get_session()
                if not session:
                    return None
                data = session.quotes({"symbols": normalized})
            if data.get("s") != "ok" or not data.get("d"):
                return None
            return data["d"][0]["v"]["lp"]
        except Exception as e:
            logger.error(f"LTP fetch failed for {scrip}: {e}")
            return None

    def _normalize_symbol(self, symbol: str) -> str:
        return FYERS_SYMBOL.get(symbol.upper(), f"NSE:{symbol.upper()}-EQ")

    def _fetch_quotes(self, symbols: list, session) -> list:
        try:
            syms = ",".join(symbols)
            data = session.quotes({"symbols": syms})
            if self._is_auth_error(data):
                fyers_client.invalidate()
                session = fyers_client.get_session()
                if not session:
                    return []
                data = session.quotes({"symbols": syms})
            return data.get("d", [])
        except Exception as e:
            logger.error(f"Quotes fetch failed: {e}")
            return []

    def _process_quotes(self, df: pd.DataFrame, session, scrip: str) -> list:
        try:
            syms = df[9].head(15).tolist()
            quotes = self._fetch_quotes(syms, session)
            details = {
                r[9]: {
                    "lot": LOT_SIZES.get(scrip.upper(), int(float(r[3])) if r[3] else 0),
                    "strike": float(r[15]) if r[15] else 0.0,
                }
                for _, r in df.iterrows()
            }

            processed = []
            for q in sorted(quotes, key=lambda x: x["v"]["volume"], reverse=True):
                v = q["v"]
                name = q["n"]
                lot = details.get(name, {}).get("lot", 0)
                strike = details.get(name, {}).get("strike", 0)
                lp = v["lp"]
                vol = v["volume"]
                net_value = lot * lp
                if net_value >= 40000:
                    continue

                bid = v["bid"][0][0] if isinstance(v.get("bid"), list) and v["bid"] else v.get("bid")
                ask = v["ask"][0][0] if isinstance(v.get("ask"), list) and v["ask"] else v.get("ask")
                spread = (bid - ask) / bid if bid and ask and bid != 0 else None

                processed.append(
                    {
                        "instrument": name.replace("NSE:", "").replace("BSE:", ""),
                        "lp": lp,
                        "lot_size": int(lot),
                        "strike": float(strike) if strike else 0.0,
                        "volume": vol,
                        "net_value": net_value,
                        "spread": spread,
                    }
                )
            return processed
        except Exception as e:
            logger.error(f"Quote processing error: {e}")
            return []

    def get_best_instrument(self, scrip: str, direction: str) -> dict | None:
        try:
            df = self._fetch_csv(scrip)
            if df is None:
                return None

            df = self._extract_expiry_dates(df)
            if df is None:
                return None

            expiry, days_to_expiry = self._select_expiry(scrip, df)
            if not expiry:
                return None

            df = df[df["date"].dt.date == expiry]
            session = fyers_client.get_session()
            if not session:
                return None

            df, atm, stock_ltp = self._build_strike_chain(df, scrip, direction)
            if df is None:
                return None

            processed = self._process_quotes(df, session, scrip)
            del df
            gc.collect()

            if not processed:
                return None

            return {
                "processed": processed,
                "atm": atm,
                "stock_ltp": stock_ltp,
                "expiry": expiry,
                "days_to_expiry": days_to_expiry,
            }
        except Exception as e:
            logger.error(f"Option chain error for {scrip}: {e}")
            return None


option_chain_service = OptionChainService()
