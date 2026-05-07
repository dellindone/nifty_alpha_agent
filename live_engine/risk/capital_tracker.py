from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from db import get_engine  # backward compatibility for older tests/fixtures

logger = logging.getLogger(__name__)

SNAPSHOT_COLUMNS = ["timestamp", "capital", "daily_pnl", "cumulative_pnl", "open_margin_used", "event"]


@dataclass
class CapitalSnapshot:
    timestamp: datetime
    capital: float
    daily_pnl: float
    cumulative_pnl: float
    open_margin_used: float
    event: str


class CapitalTracker:
    """Static configured-capital guard.

    This intentionally does not maintain a moving PnL ledger anymore. Capital
    shown in the app comes directly from settings / env, while available buying
    power is simply configured capital minus margin reserved for currently open
    trades in this process.
    """

    INITIAL_CAPITAL = float(os.getenv("INITIAL_CAPITAL", "100000"))

    def __init__(
        self,
        data_dir: Path | None = None,
        initial_capital: float | None = None,
        capital_path: Path | None = None,
    ) -> None:
        self.capital_path = Path(capital_path) if capital_path is not None else Path(data_dir or "data") / "capital.parquet"
        self.capital_path.parent.mkdir(parents=True, exist_ok=True)
        self.initial_capital = float(self.INITIAL_CAPITAL if initial_capital is None else initial_capital)
        self._reserved_margin: dict[str, float] = {}
        self._released_trades: set[str] = set()
        logger.info("capital_tracker static_mode initial=%.2f", self.initial_capital)

    def get_available_capital(self) -> float:
        return max(0.0, self.initial_capital - self._open_margin_used())

    def get_current_capital(self) -> float:
        return float(self.initial_capital)

    @property
    def current_capital(self) -> float:
        return self.get_current_capital()

    def reserve_margin(self, trade_id: str, amount: float) -> bool:
        margin = max(0.0, float(amount))
        if self.get_available_capital() < margin:
            logger.info(
                "capital_reserve_failed trade_id=%s amount=%.2f available=%.2f",
                trade_id,
                margin,
                self.get_available_capital(),
            )
            return False
        self._reserved_margin[str(trade_id)] = margin
        return True

    def release_margin(self, trade_id: str, pnl_net: float) -> None:
        tid = str(trade_id)
        if tid in self._released_trades:
            logger.warning("release_margin called twice for trade_id=%s — skipping", tid)
            return
        self._released_trades.add(tid)
        self._reserved_margin.pop(tid, None)

    def apply_realized_pnl(self, pnl: float, timestamp: datetime | None = None):
        return {
            "timestamp": timestamp or datetime.now(timezone.utc),
            "capital": self.current_capital,
            "daily_pnl": 0.0,
            "cumulative_pnl": 0.0,
            "open_margin_used": self._open_margin_used(),
            "event": "EXIT",
        }

    def snapshot(self, event: str, timestamp: datetime | None = None) -> None:
        return None

    def _load_parquet(self) -> pd.DataFrame:
        return pd.DataFrame(columns=SNAPSHOT_COLUMNS)

    def load_history(self) -> pd.DataFrame:
        return pd.DataFrame(columns=SNAPSHOT_COLUMNS)

    def daily_pnl_series(self) -> pd.Series:
        return pd.Series(dtype=float)

    def _open_margin_used(self) -> float:
        return float(sum(self._reserved_margin.values()))
