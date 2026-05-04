from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import Column, DateTime, Float, Integer, MetaData, Table, Text, insert, select
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

_COLUMNS = [
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("timestamp", DateTime, nullable=False),
    Column("capital", Float, nullable=False),
    Column("daily_pnl", Float, nullable=False),
    Column("cumulative_pnl", Float, nullable=False),
    Column("open_margin_used", Float, nullable=False),
    Column("event", Text, nullable=False),
]

_table_cache: dict[str, Table] = {}


def _get_table(table_name: str) -> Table:
    if table_name not in _table_cache:
        meta = MetaData()
        _table_cache[table_name] = Table(table_name, meta, *[c.copy() for c in _COLUMNS])
    return _table_cache[table_name]


def ensure_capital_table(engine: Engine | None, table_name: str = "capital_snapshot") -> None:
    if engine is None:
        return
    try:
        table = _get_table(table_name)
        table.metadata.create_all(engine, tables=[table], checkfirst=True)
    except Exception as exc:
        logger.warning("Failed to ensure %s exists: %s", table_name, exc)


def append_capital_snapshot(engine: Engine | None, record: dict, table_name: str = "capital_snapshot") -> None:
    if engine is None:
        return
    try:
        table = _get_table(table_name)
        row = {c.name: record[c.name] for c in table.columns if c.name != "id" and c.name in record}
        with engine.begin() as conn:
            conn.execute(insert(table).values(**row))
    except Exception as exc:
        logger.warning("Failed to insert capital snapshot into %s: %s", table_name, exc)


def load_capital_history(engine: Engine | None, table_name: str = "capital_snapshot") -> pd.DataFrame | None:
    if engine is None:
        return None
    try:
        table = _get_table(table_name)
        stmt = select(table).order_by(table.c.timestamp, table.c.id)
        with engine.connect() as conn:
            rows = [dict(r._mapping) for r in conn.execute(stmt)]
        return pd.DataFrame(rows)
    except Exception as exc:
        logger.warning("DB load_capital_history failed (%s): %s", table_name, exc)
        return None
