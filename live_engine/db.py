from __future__ import annotations

import logging
import os
from datetime import date, datetime

import pandas as pd
from sqlalchemy import Boolean, Column, Date, DateTime, Float, Integer, MetaData, Table, Text, create_engine, inspect, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)
metadata = MetaData()
paper_trade = Table("paper_trade", metadata, Column("trade_id", Text, primary_key=True), Column("instrument", Text, nullable=False), Column("timestamp_entry", DateTime, nullable=False), Column("timestamp_exit", DateTime), Column("direction", Integer, nullable=False), Column("strike", Integer), Column("expiry_date", Date), Column("option_type", Text), Column("entry_premium", Float), Column("exit_premium", Float), Column("lot_size", Integer), Column("lots", Integer), Column("trail_bin", Text), Column("trail_tf", Text), Column("vix_at_entry", Float), Column("entry_price", Float), Column("exit_price", Float), Column("contracts", Float), Column("pnl_usd", Float), Column("charges_usd", Float), Column("initial_sl_price", Float), Column("sl_price", Float, nullable=False), Column("target_price", Float, nullable=False), Column("confidence", Float, nullable=False), Column("direction_prob", Float, nullable=False), Column("exit_reason", Text), Column("pnl_gross", Float), Column("pnl_net", Float), Column("charges", Float), Column("atr_at_entry", Float, nullable=False), Column("override", Boolean, nullable=False, server_default=text("false")), Column("trail_active", Boolean, nullable=False, server_default=text("false")), Column("current_sl", Float), Column("highest_premium", Float), Column("model_version", Text, nullable=False), Column("account_name", Text), Column("broker_name", Text), Column("option_symbol", Text))
live_trade = Table("live_trade", metadata, Column("trade_id", Text, primary_key=True), Column("account_name", Text), Column("broker_name", Text), Column("broker_order_id", Text), Column("broker_exit_order_id", Text), Column("trade_state", Text, nullable=False), Column("fill_price", Float), Column("exit_fill_price", Float), Column("instrument", Text, nullable=False), Column("direction", Integer, nullable=False), Column("option_type", Text), Column("strike", Integer), Column("expiry_date", Date), Column("entry_premium", Float), Column("exit_premium", Float), Column("lot_size", Integer), Column("lots", Integer), Column("sl_price", Float, nullable=False), Column("current_sl", Float), Column("target_price", Float, nullable=False), Column("highest_premium", Float), Column("trail_active", Boolean, nullable=False, server_default=text("false")), Column("trail_bin", Text), Column("trail_tf", Text), Column("vix_at_entry", Float), Column("atr_at_entry", Float, nullable=False), Column("confidence", Float, nullable=False), Column("direction_prob", Float, nullable=False), Column("model_version", Text, nullable=False), Column("exit_reason", Text), Column("pnl_gross", Float), Column("pnl_net", Float), Column("charges", Float), Column("override", Boolean, nullable=False, server_default=text("false")), Column("timestamp_entry", DateTime, nullable=False), Column("timestamp_exit", DateTime))
_engine_singleton: Engine | None = None


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def get_engine() -> Engine | None:
    global _engine_singleton
    if _engine_singleton is not None:
        return _engine_singleton
    raw_url = os.getenv("DATABASE_URL", "").strip()
    if not raw_url:
        logger.warning("DATABASE_URL not set; DB persistence disabled.")
        return None
    try:
        _engine_singleton = create_engine(_normalize_database_url(raw_url), future=True, pool_pre_ping=True, pool_size=2, max_overflow=3)
        return _engine_singleton
    except Exception as exc:
        logger.warning("Failed to create DB engine: %s", exc)
        return None


def ensure_table_exists(engine: Engine | None) -> None:
    if engine is None:
        return
    try:
        metadata.create_all(engine, tables=[paper_trade, live_trade], checkfirst=True)
        _ensure_override_column_exists(engine)
    except Exception as exc:
        logger.warning("Failed to ensure DB tables exist: %s", exc)


def _ensure_override_column_exists(engine: Engine) -> None:
    try:
        cols = {c["name"] for c in inspect(engine).get_columns("paper_trade")}
        missing = {"override": "BOOLEAN NOT NULL DEFAULT false", "initial_sl_price": "FLOAT", "lots": "INTEGER", "trail_active": "BOOLEAN NOT NULL DEFAULT false", "current_sl": "FLOAT", "highest_premium": "FLOAT", "account_name": "TEXT", "broker_name": "TEXT", "option_symbol": "TEXT"}
        with engine.begin() as conn:
            for name, ddl in missing.items():
                if name not in cols:
                    conn.execute(text(f"ALTER TABLE paper_trade ADD COLUMN {name} {ddl}"))
                    logger.info("Added missing paper_trade.%s column", name)
    except Exception as exc:
        logger.warning("Failed to add missing columns on paper_trade: %s", exc)


def _is_nat_or_nan(val: object) -> bool:
    try:
        return val is not None and val != val
    except Exception:
        return False


def _normalize_record(record: dict) -> dict:
    row = {k: (v.item() if type(v).__module__ == "numpy" else v) for k, v in record.items()}
    for key in ("timestamp_entry", "timestamp_exit"):
        val = row.get(key)
        row[key] = None if val is None or _is_nat_or_nan(val) else val if isinstance(val, datetime) else datetime.fromisoformat(str(val)[:19]) if str(val) else None
    expiry = row.get("expiry_date")
    row["expiry_date"] = None if expiry is None or _is_nat_or_nan(expiry) else expiry if isinstance(expiry, date) else expiry.date() if hasattr(expiry, "date") else date.fromisoformat(str(expiry)[:10])
    return row


def _upsert_stmt(engine: Engine, table: Table, row: dict):
    insert_fn = pg_insert if engine.dialect.name == "postgresql" else sqlite_insert
    stmt = insert_fn(table).values(**row)
    return stmt.on_conflict_do_update(index_elements=[table.c.trade_id], set_={c.name: stmt.excluded[c.name] for c in table.columns if c.name != "trade_id"})


def _upsert(engine: Engine | None, table: Table, record: dict) -> None:
    if engine is None:
        return
    try:
        row = {k: v for k, v in _normalize_record(record).items() if k in {c.name for c in table.columns}}
        with engine.begin() as conn:
            conn.execute(_upsert_stmt(engine, table, row))
    except Exception as exc:
        logger.warning("Failed to upsert %s into DB: %s", table.name, exc)


def upsert_trade(engine: Engine | None, record: dict) -> None:
    _upsert(engine, paper_trade, record)


def upsert_live_trade(engine: Engine | None, record: dict) -> None:
    _upsert(engine, live_trade, record)


def load_live_trades(engine: Engine | None) -> pd.DataFrame:
    if engine is None:
        return pd.DataFrame()
    try:
        with engine.connect() as conn:
            df = pd.read_sql(select(live_trade).order_by(live_trade.c.timestamp_entry), conn)
        return df
    except Exception as exc:
        logger.warning("load_live_trades failed: %s", exc)
        return pd.DataFrame()


def check_db_health(engine) -> tuple[str, str]:
    if engine is None:
        return "warn", "no DB engine (parquet-only mode)"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok", ""
    except Exception as exc:
        return "critical", str(exc)
