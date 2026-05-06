"""Base journal — shared parquet read/write logic for all agent journals."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd

from utils.time_utils import to_ist_series

logger = logging.getLogger(__name__)


class BaseJournal(ABC):
    """
    Owns parquet persistence. Subclasses define their column schema
    and implement the trade lifecycle (log_entry, log_exit, load_all).
    """

    def __init__(self, data_dir: Path, filename: str) -> None:
        self.data_dir    = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.trades_path = self.data_dir / filename

    # ── Schema contract (subclasses define) ──────────────────────────────────

    @property
    @abstractmethod
    def _columns(self) -> list[str]:
        """All column names for this journal's parquet schema."""
        ...

    @property
    @abstractmethod
    def _datetime_columns(self) -> list[str]:
        """Subset of _columns that hold timestamps."""
        ...

    # ── Trade lifecycle (subclasses implement) ────────────────────────────────

    @abstractmethod
    def log_entry(self, record) -> None: ...

    @abstractmethod
    def log_exit(self, *args, **kwargs) -> None: ...

    @abstractmethod
    def load_all(self) -> pd.DataFrame: ...

    @abstractmethod
    def load_open_trades(self) -> pd.DataFrame: ...

    # ── Shared parquet I/O ────────────────────────────────────────────────────

    def _ensure_shape(self, df: pd.DataFrame) -> pd.DataFrame:
        shaped = df.copy()
        for col in self._columns:
            if col not in shaped.columns:
                shaped[col] = pd.NaT if col in self._datetime_columns else None
        for col in self._datetime_columns:
            shaped[col] = to_ist_series(shaped[col])
        return shaped[self._columns]

    def _read_parquet(self) -> pd.DataFrame:
        if not self.trades_path.exists():
            return pd.DataFrame(columns=self._columns)
        try:
            df = pd.read_parquet(self.trades_path, engine="pyarrow")
        except Exception:
            df = pd.read_parquet(self.trades_path)
        return self._ensure_shape(df)

    def _write_parquet(self, df: pd.DataFrame) -> None:
        frame = self._ensure_shape(df)
        try:
            frame.to_parquet(self.trades_path, index=False, engine="pyarrow")
        except Exception:
            frame.to_parquet(self.trades_path, index=False)
