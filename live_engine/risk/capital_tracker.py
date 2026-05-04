from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from config.settings import Trading
from db import get_engine
from db_capital import append_capital_snapshot, ensure_capital_table, load_capital_history

logger = logging.getLogger(__name__)

_AGENT_MODE = os.getenv("AGENT_MODE", "SHADOW").upper()
_INSTRUMENT = os.getenv("INSTRUMENT", "NIFTY").upper().replace(" ", "")
_CAPITAL_TABLE = f"capital_snapshot_{_INSTRUMENT}_{_AGENT_MODE}".lower()


@dataclass
class CapitalSnapshot:
    timestamp: datetime
    capital: float
    daily_pnl: float
    cumulative_pnl: float
    open_margin_used: float
    event: str


SNAPSHOT_COLUMNS = ["timestamp", "capital", "daily_pnl", "cumulative_pnl", "open_margin_used", "event"]


class CapitalTracker:
    INITIAL_CAPITAL = Trading.INITIAL_CAPITAL

    def __init__(self, data_dir: Path | None = None, initial_capital: float | None = None, capital_path: Path | None = None) -> None:
        self.capital_path = Path(capital_path) if capital_path is not None else Path(data_dir or "model_improver/data") / "capital.parquet"
        self.capital_path.parent.mkdir(parents=True, exist_ok=True)
        self.initial_capital = float(self.INITIAL_CAPITAL if initial_capital is None else initial_capital)
        self._table = _CAPITAL_TABLE
        self._engine = get_engine(); ensure_capital_table(self._engine, self._table); self._reserved_margin: dict[str, float] = {}; self._released_trades: set[str] = set(); self._current_capital = self.initial_capital; self._cumulative_pnl = 0.0
        logger.info("capital_tracker mode=%s table=%s initial=%.2f", _AGENT_MODE, self._table, self.initial_capital)
        history = self.load_history()
        if history.empty: self.snapshot(event="INIT")
        else: self._current_capital, self._cumulative_pnl = float(history.iloc[-1]["capital"]), float(history.iloc[-1]["cumulative_pnl"])

    def get_available_capital(self) -> float: return max(0.0, self._current_capital - self._open_margin_used())
    def get_current_capital(self) -> float: return float(self._current_capital)
    @property
    def current_capital(self) -> float: return self.get_current_capital()

    def reserve_margin(self, trade_id: str, amount: float) -> bool:
        margin = max(0.0, float(amount))
        if self.get_available_capital() < margin:
            logger.info("capital_reserve_failed trade_id=%s amount=%.2f available=%.2f", trade_id, margin, self.get_available_capital()); return False
        self._reserved_margin[str(trade_id)] = margin; self.snapshot(event="ENTRY"); return True

    def release_margin(self, trade_id: str, pnl_net: float) -> None:
        tid = str(trade_id)
        if tid in self._released_trades:
            logger.warning("release_margin called twice for trade_id=%s — skipping", tid); return
        self._released_trades.add(tid); self._reserved_margin.pop(tid, None); self._cumulative_pnl += float(pnl_net); self._current_capital = self.initial_capital + self._cumulative_pnl; self.snapshot(event="EXIT")

    def apply_realized_pnl(self, pnl: float, timestamp: datetime | None = None):
        self._cumulative_pnl += float(pnl); self._current_capital = self.initial_capital + self._cumulative_pnl; self.snapshot(event="EXIT", timestamp=timestamp); return self.load_history().iloc[-1]

    def snapshot(self, event: str, timestamp: datetime | None = None) -> None:
        ts = timestamp or datetime.now(timezone.utc); daily_series = self.daily_pnl_series(); row = CapitalSnapshot(timestamp=ts, capital=float(self._current_capital), daily_pnl=float(daily_series.get(ts.date(), 0.0)), cumulative_pnl=float(self._cumulative_pnl), open_margin_used=float(self._open_margin_used()), event=str(event))
        if self._engine is not None:
            append_capital_snapshot(self._engine, asdict(row), self._table)
        else:
            history = self._load_parquet(); updated = pd.concat([history, pd.DataFrame([asdict(row)])], ignore_index=True); updated.to_parquet(self.capital_path, index=False, engine="pyarrow")

    def _load_parquet(self) -> pd.DataFrame:
        if not self.capital_path.exists(): return pd.DataFrame(columns=SNAPSHOT_COLUMNS)
        try: df = pd.read_parquet(self.capital_path, engine="pyarrow")
        except Exception: df = pd.read_parquet(self.capital_path)
        for column in SNAPSHOT_COLUMNS:
            if column not in df.columns: df[column] = None
        return df[SNAPSHOT_COLUMNS].copy()

    def load_history(self) -> pd.DataFrame:
        db_df = load_capital_history(self._engine, self._table)
        if db_df is not None:
            for column in SNAPSHOT_COLUMNS:
                if column not in db_df.columns: db_df[column] = None
            return db_df[SNAPSHOT_COLUMNS].copy()
        return self._load_parquet()

    def daily_pnl_series(self) -> pd.Series:
        history = self.load_history()
        if history.empty: return pd.Series(dtype=float)
        ts = pd.to_datetime(history["timestamp"], errors="coerce"); cum = pd.to_numeric(history["cumulative_pnl"], errors="coerce").fillna(0.0); frame = pd.DataFrame({"date": ts.dt.date, "cum": cum}).dropna()
        if frame.empty: return pd.Series(dtype=float)
        end_of_day = frame.groupby("date", as_index=True)["cum"].last()
        return end_of_day.diff().fillna(end_of_day.iloc[0])

    def _open_margin_used(self) -> float: return float(sum(self._reserved_margin.values()))
