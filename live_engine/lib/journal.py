"""Shadow trade journal with DB-primary and parquet-backup persistence."""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd
from sqlalchemy import select


from base.journal import BaseJournal
from utils.charge_calculator import calculate_charges
from db import ensure_table_exists, get_engine, paper_trade, upsert_trade
from config.settings import Paths

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    trade_id: str
    instrument: str
    timestamp_entry: datetime
    timestamp_exit: datetime | None
    direction: int
    strike: int
    expiry_date: date
    option_type: str
    entry_premium: float
    exit_premium: float | None
    lot_size: int
    lots: int
    sl_price: float
    target_price: float
    trail_bin: str
    trail_tf: str
    confidence: float
    direction_prob: float
    exit_reason: str | None
    pnl_gross: float | None
    pnl_net: float | None
    charges: float | None
    vix_at_entry: float
    atr_at_entry: float
    model_version: str


TRADE_COLUMNS = [
    "trade_id",
    "instrument",
    "timestamp_entry",
    "timestamp_exit",
    "direction",
    "strike",
    "expiry_date",
    "option_type",
    "entry_premium",
    "exit_premium",
    "current_sl",
    "highest_premium",
    "trail_active",
    "lot_size",
    "lots",
    "sl_price",
    "target_price",
    "trail_bin",
    "trail_tf",
    "confidence",
    "direction_prob",
    "exit_reason",
    "pnl_gross",
    "pnl_net",
    "charges",
    "vix_at_entry",
    "atr_at_entry",
    "model_version",
]


def _read_parquet(path: Path) -> pd.DataFrame:
    try:
        return pd.read_parquet(path, engine="pyarrow")
    except Exception:
        return pd.read_parquet(path, engine="fastparquet")


def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    try:
        df.to_parquet(path, index=False, engine="pyarrow")
    except Exception:
        df.to_parquet(path, index=False, engine="fastparquet")


class Journal(BaseJournal):
    @property
    def _columns(self) -> list[str]:
        return TRADE_COLUMNS

    @property
    def _datetime_columns(self) -> list[str]:
        return ["timestamp_entry", "timestamp_exit"]

    def __init__(self, data_dir: Path) -> None:
        super().__init__(data_dir, "trades.parquet")
        self._engine = None
        if not os.getenv("DATABASE_URL", "").strip():
            logger.warning("DATABASE_URL missing; Journal will use parquet backup only.")
        else:
            self._engine = get_engine()
            ensure_table_exists(self._engine)

    def _load_from_parquet(self) -> pd.DataFrame:
        if not self.trades_path.exists():
            return pd.DataFrame(columns=TRADE_COLUMNS)
        try:
            return self._ensure_shape(_read_parquet(self.trades_path))
        except Exception as exc:
            logger.warning("Failed to read trades parquet %s: %s", self.trades_path, exc)
            return pd.DataFrame(columns=TRADE_COLUMNS)

    def _load_all_from_db(self) -> pd.DataFrame | None:
        if self._engine is None:
            return None
        try:
            stmt = select(paper_trade).order_by(paper_trade.c.timestamp_entry)
            with self._engine.connect() as conn:
                result = conn.execute(stmt)
                rows = [dict(row._mapping) for row in result]
            df = pd.DataFrame(rows)
            if df.empty:
                return pd.DataFrame(columns=TRADE_COLUMNS)
            return self._ensure_shape(df)
        except Exception as exc:
            logger.warning("DB load_all failed, falling back to parquet: %s", exc)
            return None

    def _load_open_from_db(self) -> pd.DataFrame | None:
        if self._engine is None:
            return None
        try:
            stmt = (
                select(paper_trade)
                .where(paper_trade.c.timestamp_exit.is_(None))
                .order_by(paper_trade.c.timestamp_entry)
            )
            with self._engine.connect() as conn:
                result = conn.execute(stmt)
                rows = [dict(row._mapping) for row in result]
            df = pd.DataFrame(rows)
            if df.empty:
                return pd.DataFrame(columns=TRADE_COLUMNS)
            return self._ensure_shape(df)
        except Exception as exc:
            logger.warning("DB load_open_trades failed, falling back to parquet: %s", exc)
            return None

    def load_all(self) -> pd.DataFrame:
        db_df = self._load_all_from_db()
        if db_df is not None:
            return db_df
        return self._load_from_parquet()

    def load_open_trades(self) -> pd.DataFrame:
        db_df = self._load_open_from_db()
        if db_df is not None:
            return db_df
        all_trades = self._load_from_parquet()
        if all_trades.empty:
            return all_trades
        return all_trades[all_trades["timestamp_exit"].isna()].copy()

    def _persist(self, df: pd.DataFrame) -> None:
        _write_parquet(self._ensure_shape(df), self.trades_path)

    def log_entry(self, record: TradeRecord) -> None:
        row = asdict(record)
        if not row.get("trade_id"):
            row["trade_id"] = str(uuid4())

        all_trades = self._load_from_parquet()
        new_row = pd.DataFrame([row]).dropna(axis=1, how="all")
        updated = pd.concat([all_trades, new_row], ignore_index=True)
        self._persist(updated)
        upsert_trade(self._engine, row)

    def log_exit(
        self,
        trade_id: str,
        exit_premium: float,
        exit_reason: str,
        timestamp_exit: datetime,
        pnl_gross: float | None = None,
        pnl_net: float | None = None,
        charges: float | None = None,
    ) -> None:
        # Use load_all() (DB-first) so restored trades that exist only in DB are found.
        all_trades = self.load_all()
        if all_trades.empty:
            logger.warning("log_exit called for %s but journal is empty", trade_id)
            return

        mask = all_trades["trade_id"].astype(str) == str(trade_id)
        if not mask.any():
            logger.warning("Trade ID %s not found for exit logging", trade_id)
            return

        row = all_trades.loc[mask].iloc[-1]
        exit_premium_val = float(exit_premium)

        if pnl_gross is None or pnl_net is None or charges is None:
            instrument = str(row["instrument"]).upper()
            lot_size = int(float(row["lot_size"]))
            lots = int(float(row["lots"])) if "lots" in row.index and row["lots"] else 1
            entry_premium_val = float(row["entry_premium"])
            pnl_gross = (exit_premium_val - entry_premium_val) * lot_size * lots
            charges = calculate_charges(
                premium=exit_premium_val,
                lot_size=lot_size,
                lots=lots,
                instrument=instrument,
                side="SELL",
            )["total"]
            pnl_net = pnl_gross - float(charges)

        exit_updates = {
            "timestamp_exit": timestamp_exit,
            "exit_premium": exit_premium_val,
            "exit_reason": str(exit_reason),
            "pnl_gross": float(pnl_gross),
            "charges": float(charges),
            "pnl_net": float(pnl_net),
        }

        # Update parquet if the trade record exists there.
        parquet_trades = self._load_from_parquet()
        if not parquet_trades.empty:
            p_mask = parquet_trades["trade_id"].astype(str) == str(trade_id)
            if p_mask.any():
                for col, val in exit_updates.items():
                    if col in ("timestamp_entry", "timestamp_exit") and val is not None:
                        ts = pd.Timestamp(val)
                        val = ts.tz_convert("UTC") if ts.tzinfo is not None else ts.tz_localize("UTC")
                    parquet_trades.loc[p_mask, col] = val
                self._persist(parquet_trades)

        # Always update DB (primary source).
        updated_row = dict(row) | exit_updates
        upsert_trade(self._engine, updated_row)

    def update_trade(self, trade_id: str, updates: dict) -> None:
        all_trades = self._load_from_parquet()
        if all_trades.empty:
            return
        mask = all_trades["trade_id"].astype(str) == str(trade_id)
        if not mask.any():
            return
        for key, value in updates.items():
            if key in all_trades.columns:
                all_trades.loc[mask, key] = value
        self._persist(all_trades)
        updated_row = (
            all_trades.loc[mask]
            .sort_values("timestamp_entry")
            .iloc[-1]
            .to_dict()
        )
        upsert_trade(self._engine, updated_row)

    def update_trade_state(self, trade_id: str, *, current_sl: float, highest_premium: float, trail_active: bool = False, lots: int | None = None) -> None:
        all_trades = self._load_from_parquet()
        if all_trades.empty:
            return
        mask = all_trades["trade_id"].astype(str) == str(trade_id)
        if not mask.any():
            return
        all_trades.loc[mask, "current_sl"] = float(current_sl)
        all_trades.loc[mask, "highest_premium"] = float(highest_premium)
        all_trades.loc[mask, "trail_active"] = bool(trail_active)
        if lots is not None:
            all_trades.loc[mask, "lots"] = int(lots)
        self._persist(all_trades)
        updated_row = (
            all_trades.loc[mask]
            .sort_values("timestamp_entry")
            .iloc[-1]
            .to_dict()
        )
        upsert_trade(self._engine, updated_row)

    def open_trades(self) -> pd.DataFrame:
        return self.load_open_trades()

    def closed_trades(self) -> pd.DataFrame:
        all_trades = self.load_all()
        if all_trades.empty:
            return all_trades
        return all_trades[all_trades["timestamp_exit"].notna()].copy()


TradeJournal = Journal
