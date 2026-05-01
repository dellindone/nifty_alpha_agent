from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import Column, DateTime, Float, Integer, MetaData, Table, Text, insert, select
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)
metadata = MetaData()
capital_snapshot = Table("capital_snapshot", metadata, Column("id", Integer, primary_key=True, autoincrement=True), Column("timestamp", DateTime, nullable=False), Column("capital", Float, nullable=False), Column("daily_pnl", Float, nullable=False), Column("cumulative_pnl", Float, nullable=False), Column("open_margin_used", Float, nullable=False), Column("event", Text, nullable=False))


def ensure_capital_table(engine: Engine | None) -> None:
    if engine is None:
        return
    try:
        metadata.create_all(engine, tables=[capital_snapshot], checkfirst=True)
    except Exception as exc:
        logger.warning("Failed to ensure capital_snapshot exists: %s", exc)


def append_capital_snapshot(engine: Engine | None, record: dict) -> None:
    if engine is None:
        return
    try:
        row = {c.name: record[c.name] for c in capital_snapshot.columns if c.name != "id" and c.name in record}
        with engine.begin() as conn:
            conn.execute(insert(capital_snapshot).values(**row))
    except Exception as exc:
        logger.warning("Failed to insert capital snapshot: %s", exc)


def load_capital_history(engine: Engine | None) -> pd.DataFrame | None:
    if engine is None:
        return None
    try:
        stmt = select(capital_snapshot).order_by(capital_snapshot.c.timestamp, capital_snapshot.c.id)
        with engine.connect() as conn:
            rows = [dict(r._mapping) for r in conn.execute(stmt)]
        return pd.DataFrame(rows)
    except Exception as exc:
        logger.warning("DB load_capital_history failed, falling back to parquet: %s", exc)
        return None
