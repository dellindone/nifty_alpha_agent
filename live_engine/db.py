"""Database helpers for shadow paper-trade persistence."""

from __future__ import annotations

import logging
import os
from datetime import date, datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Float, Integer, MetaData, Table, Text, create_engine, inspect, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

metadata = MetaData()

paper_trade = Table(
    "paper_trade",
    metadata,
    Column("trade_id", Text, primary_key=True),
    Column("instrument", Text, nullable=False),
    Column("timestamp_entry", DateTime, nullable=False),
    Column("timestamp_exit", DateTime, nullable=True),
    Column("direction", Integer, nullable=False),      # Nifty: 1=CE/0=PE | BTC: 1=long/-1=short

    # Nifty options columns (nullable — BTC leaves these None)
    Column("strike", Integer, nullable=True),
    Column("expiry_date", Date, nullable=True),
    Column("option_type", Text, nullable=True),        # Nifty: CE/PE | BTC: LONG/SHORT
    Column("entry_premium", Float, nullable=True),
    Column("exit_premium", Float, nullable=True),
    Column("lot_size", Integer, nullable=True),
    Column("lots", Integer, nullable=True),
    Column("trail_bin", Text, nullable=True),
    Column("trail_tf", Text, nullable=True),
    Column("vix_at_entry", Float, nullable=True),

    # BTC futures columns (nullable — Nifty leaves these None)
    Column("entry_price", Float, nullable=True),
    Column("exit_price", Float, nullable=True),
    Column("contracts", Float, nullable=True),
    Column("pnl_usd", Float, nullable=True),
    Column("charges_usd", Float, nullable=True),
    Column("initial_sl_price", Float, nullable=True),

    # Shared columns
    Column("sl_price", Float, nullable=False),
    Column("target_price", Float, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("direction_prob", Float, nullable=False),
    Column("exit_reason", Text, nullable=True),
    Column("pnl_gross", Float, nullable=True),
    Column("pnl_net", Float, nullable=True),           # always in INR
    Column("charges", Float, nullable=True),           # always in INR
    Column("atr_at_entry", Float, nullable=False),
    Column("override", Boolean, nullable=False, server_default=text("false")),
    Column("trail_active", Boolean, nullable=False, server_default=text("false")),
    Column("current_sl", Float, nullable=True),
    Column("highest_premium", Float, nullable=True),
    Column("model_version", Text, nullable=False),
    Column("model_name", Text, nullable=True),
    Column("option_symbol", Text, nullable=True),
)


live_trade = Table(
    "live_trade",
    metadata,
    Column("trade_id", Text, primary_key=True),
    Column("instrument", Text, nullable=False),
    Column("timestamp_entry", DateTime, nullable=False),
    Column("timestamp_exit", DateTime, nullable=True),
    Column("direction", Integer, nullable=False),
    Column("option_type", Text, nullable=True),
    Column("strike", Integer, nullable=True),
    Column("expiry_date", Date, nullable=True),
    Column("entry_premium", Float, nullable=True),
    Column("exit_premium", Float, nullable=True),
    Column("lot_size", Integer, nullable=True),
    Column("lots", Integer, nullable=True),
    Column("sl_price", Float, nullable=False),
    Column("current_sl", Float, nullable=True),
    Column("target_price", Float, nullable=False),
    Column("highest_premium", Float, nullable=True),
    Column("trail_active", Boolean, nullable=False, server_default=text("false")),
    Column("trail_bin", Text, nullable=True),
    Column("trail_tf", Text, nullable=True),
    Column("vix_at_entry", Float, nullable=True),
    Column("atr_at_entry", Float, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("direction_prob", Float, nullable=False),
    Column("model_version", Text, nullable=False),
    Column("trade_state", Text, nullable=False),
    Column("exit_reason", Text, nullable=True),
    Column("pnl_gross", Float, nullable=True),
    Column("pnl_net", Float, nullable=True),
    Column("charges", Float, nullable=True),
    Column("option_symbol", Text, nullable=True),
    Column("account_name", Text, nullable=True),
    Column("broker_name", Text, nullable=True),
)


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


_engine_singleton: Engine | None = None


def get_engine() -> Engine | None:
    global _engine_singleton
    if _engine_singleton is not None:
        return _engine_singleton
    raw_url = os.getenv("DATABASE_URL", "").strip()
    if not raw_url:
        logger.warning("DATABASE_URL not set; DB persistence disabled.")
        return None
    db_url = _normalize_database_url(raw_url)
    try:
        _engine_singleton = create_engine(
            db_url,
            future=True,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=3,
        )
        return _engine_singleton
    except Exception as exc:
        logger.warning("Failed to create DB engine: %s", exc)
        return None


def ensure_table_exists(engine: Engine | None) -> None:
    if engine is None:
        return
    try:
        metadata.create_all(engine, tables=[paper_trade], checkfirst=True)
        _ensure_override_column_exists(engine)
    except Exception as exc:
        logger.warning("Failed to ensure paper_trade table exists: %s", exc)


def _ensure_override_column_exists(engine: Engine) -> None:
    missing = {
        "override": "BOOLEAN NOT NULL DEFAULT false",
        "initial_sl_price": "FLOAT",
        "lots": "INTEGER",
        "trail_active": "BOOLEAN NOT NULL DEFAULT false",
        "current_sl": "FLOAT",
        "highest_premium": "FLOAT",
        "model_name": "TEXT",
        "option_symbol": "TEXT",
    }
    try:
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL statement_timeout = 0"))
            for name, ddl in missing.items():
                conn.execute(text(f"ALTER TABLE paper_trade ADD COLUMN IF NOT EXISTS {name} {ddl}"))
    except Exception as exc:
        logger.warning("Failed to add missing columns on paper_trade: %s", exc)


def _is_nat_or_nan(val: object) -> bool:
    """Return True for pd.NaT, float NaN, or any value that compares unequal to itself."""
    if val is None:
        return False
    try:
        return val != val  # NaT and NaN are the only values where x != x
    except Exception:
        return False


def _coerce_timestamp(val: object) -> datetime | None:
    if val is None or _is_nat_or_nan(val):
        return None
    if isinstance(val, datetime) and not _is_nat_or_nan(val):
        return val
    try:
        return datetime.fromisoformat(str(val)[:19])
    except Exception:
        return None


def _to_python_scalar(val: object) -> object:
    """Convert numpy scalar types to native Python so psycopg2 can adapt them."""
    t = type(val).__module__
    if t == "numpy":
        return val.item()
    return val


def _normalize_record(record: dict) -> dict:
    normalized = {k: _to_python_scalar(v) for k, v in record.items()}

    normalized["timestamp_entry"] = _coerce_timestamp(normalized.get("timestamp_entry"))
    normalized["timestamp_exit"] = _coerce_timestamp(normalized.get("timestamp_exit"))

    expiry = normalized.get("expiry_date")
    if expiry is None or _is_nat_or_nan(expiry):
        normalized["expiry_date"] = None
    elif not isinstance(expiry, date):
        try:
            normalized["expiry_date"] = expiry.date() if hasattr(expiry, "date") else date.fromisoformat(str(expiry)[:10])
        except Exception:
            normalized["expiry_date"] = None

    return normalized


_TABLE_COLUMNS = {c.name for c in paper_trade.columns}
_LIVE_TABLE_COLUMNS = {c.name for c in live_trade.columns}


def upsert_trade(engine: Engine | None, record: dict) -> None:
    if engine is None:
        return
    try:
        normalized = _normalize_record(record)
        normalized = {k: v for k, v in normalized.items() if k in _TABLE_COLUMNS}
        stmt = pg_insert(paper_trade).values(**normalized)
        update_cols = {
            c.name: stmt.excluded[c.name]
            for c in paper_trade.columns
            if c.name != "trade_id"
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=[paper_trade.c.trade_id],
            set_=update_cols,
        )
        with engine.begin() as conn:
            conn.execute(stmt)
    except Exception as exc:
        logger.warning("Failed to upsert trade into DB: %s", exc)


def upsert_live_trade(engine: Engine | None, record: dict) -> None:
    if engine is None:
        return
    try:
        normalized = _normalize_record(record)
        normalized = {k: v for k, v in normalized.items() if k in _LIVE_TABLE_COLUMNS}
        stmt = pg_insert(live_trade).values(**normalized)
        update_cols = {c.name: stmt.excluded[c.name] for c in live_trade.columns if c.name != "trade_id"}
        stmt = stmt.on_conflict_do_update(index_elements=[live_trade.c.trade_id], set_=update_cols)
        with engine.begin() as conn:
            conn.execute(stmt)
    except Exception as exc:
        logger.warning("Failed to upsert live_trade into DB: %s", exc)
