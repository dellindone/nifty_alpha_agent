import logging
import os
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests
from dotenv import load_dotenv

from ingestion.brokers.base import AbstractBroker

load_dotenv()
logger = logging.getLogger(__name__)
MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
INTRADAY_URL = "https://api.dhan.co/v2/charts/intraday"


class DhanBroker(AbstractBroker):
    _master = None

    def __init__(self) -> None:
        self.headers = {"access-token": os.getenv("DHAN_ACCESS_TOKEN", ""), "client-id": os.getenv("DHAN_CLIENT_ID", ""), "Content-Type": "application/json"}

    def _master_df(self):
        if self._master is None:
            self._master = pd.read_csv(MASTER_URL, low_memory=False)
        return self._master

    def _resolve_security_id(self, strike: int, option_type: str, expiry_date: date) -> str:
        symbol = f"NIFTY{expiry_date.strftime('%d%b%y').upper()}{strike}{option_type}"
        matches = self._master_df().loc[self._master_df()["SEM_TRADING_SYMBOL"].astype(str) == symbol]
        return "" if matches.empty else str(matches.iloc[0]["SEM_SMST_SECURITY_ID"])

    def _chunk(self, start: date, end: date):
        day = start
        while day <= end:
            nxt = min(day + timedelta(days=29), end)
            yield day, nxt
            day = nxt + timedelta(days=1)

    def get_historical(self, symbol: str, resolution: str, date_from: str, date_to: str) -> list:
        try:
            _, option_type, strike, expiry = symbol.split("_")
            security_id = self._resolve_security_id(int(strike), option_type, datetime.fromisoformat(expiry).date())
            if not security_id:
                return []
            rows, start, end = [], datetime.fromisoformat(date_from).date(), datetime.fromisoformat(date_to).date()
            for chunk_start, chunk_end in self._chunk(start, end):
                payload = {"securityId": security_id, "exchangeSegment": "NSE_FNO", "instrument": "OPTIDX", "expiryCode": 0, "oi": True, "fromDate": chunk_start.isoformat(), "toDate": chunk_end.isoformat()}
                data = {}
                for attempt in range(3):
                    try:
                        res = requests.post(INTRADAY_URL, json=payload, headers=self.headers, timeout=60)
                        if res.status_code == 200:
                            data = res.json()
                            break
                        logger.warning("Dhan non-200 status %s on attempt %s: %s", res.status_code, attempt, res.text[:200])
                    except Exception as e:
                        logger.error("Dhan chunk error: %s", e)
                    time.sleep(2 ** attempt)
                ts = data.get("timestamp", [])
                rows.extend([[ts[i], data["open"][i], data["high"][i], data["low"][i], data["close"][i], data["volume"][i], data.get("oi", [None] * len(ts))[i], data.get("iv", [None] * len(ts))[i]] for i in range(len(ts))])
                time.sleep(1.1)
            return rows
        except Exception as e:
            logger.error("Dhan historical error: %s", e)
            return []

    def get_quote(self, symbols: list[str]) -> list[dict]:
        raise NotImplementedError("Dhan quote endpoint not implemented")
