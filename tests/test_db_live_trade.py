from datetime import date, datetime, timezone

from sqlalchemy import create_engine, inspect, text

import db
from db import ensure_table_exists, get_engine, live_trade, upsert_live_trade, upsert_trade


def test_live_trade_table_has_columns():
    cols = {c.name for c in live_trade.columns}
    for name in {"trade_id", "account_name", "broker_name", "broker_order_id", "broker_exit_order_id", "trade_state", "fill_price", "exit_fill_price"}:
        assert name in cols


def test_upsert_live_trade_insert_and_update():
    engine = create_engine("sqlite:///:memory:", future=True)
    ensure_table_exists(engine)
    row = {"trade_id": "T1", "trade_state": "PENDING", "instrument": "NIFTY", "direction": 1, "sl_price": 10.0, "target_price": 20.0, "trail_active": False, "atr_at_entry": 15.0, "confidence": 0.7, "direction_prob": 0.8, "model_version": "v1", "override": False, "timestamp_entry": datetime.now(timezone.utc)}
    upsert_live_trade(engine, row)
    upsert_live_trade(engine, row | {"trade_state": "OPEN", "fill_price": 99.5})
    with engine.connect() as conn:
        got = conn.execute(text("select trade_state, fill_price from live_trade where trade_id='T1'")).one()
    assert got[0] == "OPEN" and got[1] == 99.5


def test_paper_trade_migration_adds_account_and_broker():
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("create table paper_trade (trade_id text primary key, instrument text not null, timestamp_entry datetime not null, timestamp_exit datetime, direction integer not null, sl_price float not null, target_price float not null, confidence float not null, direction_prob float not null, atr_at_entry float not null, model_version text not null)"))
    ensure_table_exists(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("paper_trade")}
    assert "account_name" in cols and "broker_name" in cols


def test_get_engine_and_url_normalization(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/db")
    monkeypatch.setattr(db, "_engine_singleton", None)
    assert db._normalize_database_url("postgresql://u:p@h:5432/db").startswith("postgresql+psycopg2://")
    assert get_engine() is not None


def test_get_engine_none_and_paper_upsert(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "_engine_singleton", None)
    assert get_engine() is None
    engine = create_engine("sqlite:///:memory:", future=True)
    ensure_table_exists(engine)
    upsert_trade(engine, {"trade_id": "P1", "instrument": "NIFTY", "timestamp_entry": datetime.now(timezone.utc), "direction": 1, "sl_price": 10.0, "target_price": 20.0, "confidence": 0.7, "direction_prob": 0.8, "atr_at_entry": 15.0, "model_version": "v1"})
    with engine.connect() as conn:
        assert conn.execute(text("select trade_id from paper_trade where trade_id='P1'")).one()[0] == "P1"
