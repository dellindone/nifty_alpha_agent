import datetime as dt
import uuid

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.pool import StaticPool

import db
import lib.journal as jm
from lib.journal import Journal, TRADE_COLUMNS, TradeRecord


def make_record(**k):
    d = dict(trade_id=str(uuid.uuid4()), instrument="NIFTY", timestamp_entry=dt.datetime(2026, 5, 4, 9, 15), timestamp_exit=None,
             direction=0, strike=24200, expiry_date=dt.date(2026, 5, 8), option_type="PE", entry_premium=90.0, exit_premium=None,
             lot_size=65, lots=1, sl_price=37.0, target_price=77.0, trail_bin="WIDE", trail_tf="15m", confidence=0.56,
             direction_prob=0.44, exit_reason=None, pnl_gross=None, pnl_net=None, charges=None, vix_at_entry=18.0, atr_at_entry=12.0,
             model_version="v6")
    d.update(k)
    return TradeRecord(**d)


def _upsert(engine, row):
    t = db.paper_trade
    normalized = db._normalize_record(row)
    vals = {c.name: (None if pd.isna(normalized.get(c.name)) else normalized.get(c.name)) for c in t.columns if c.name in normalized}
    s = sqlite_insert(t).values(**vals)
    with engine.begin() as c:
        c.execute(s.on_conflict_do_update(index_elements=[t.c.trade_id], set_={k: s.excluded[k] for k in vals if k != "trade_id"}))


@pytest.fixture
def parquet_journal(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return Journal(tmp_path)


@pytest.fixture
def db_journal(tmp_path, monkeypatch):
    eng = create_engine("sqlite+pysqlite:///:memory:", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    db.metadata.create_all(eng, tables=[db.paper_trade], checkfirst=True)
    monkeypatch.setenv("DATABASE_URL", "sqlite://dummy")
    monkeypatch.setattr(jm, "get_engine", lambda: eng)
    monkeypatch.setattr(jm, "ensure_table_exists", lambda _e: db.metadata.create_all(eng, tables=[db.paper_trade], checkfirst=True))
    monkeypatch.setattr(jm, "upsert_trade", lambda e, r: _upsert(e, r))
    return Journal(tmp_path)


def test_parquet_entry_exit_and_open_closed(parquet_journal):
    parquet_journal.log_entry(make_record(trade_id="t1"))
    parquet_journal.log_exit("t1", 95.0, "SL_HIT", dt.datetime(2026, 5, 4, 9, 30), pnl_gross=325.0, pnl_net=300.0, charges=25.0)
    parquet_journal.log_entry(make_record(trade_id="t2"))
    df = parquet_journal.load_all().set_index("trade_id")
    assert float(df.loc["t1", "exit_premium"]) == 95.0
    assert set(parquet_journal.load_open_trades().trade_id.astype(str)) == {"t2"}
    assert set(parquet_journal.closed_trades().trade_id.astype(str)) == {"t1"}


def test_log_exit_warnings_and_parquet_helpers(parquet_journal, caplog):
    parquet_journal.log_exit("x", 10.0, "SL_HIT", dt.datetime.now(dt.timezone.utc))
    parquet_journal.log_entry(make_record(trade_id="t1"))
    parquet_journal.log_exit("missing", 10.0, "SL_HIT", dt.datetime.now(dt.timezone.utc))
    j2 = Journal(parquet_journal.trades_path.parent / "new")
    df = pd.DataFrame([{"trade_id": "a", "instrument": "NIFTY", "timestamp_entry": dt.datetime.now(dt.timezone.utc), "timestamp_exit": None}])
    j2._persist(df)
    assert "journal is empty" in caplog.text and "not found" in caplog.text
    assert list(j2._load_from_parquet().columns) == TRADE_COLUMNS


def test_log_exit_auto_charge_calculation(parquet_journal):
    parquet_journal.log_entry(make_record(trade_id="ac1", entry_premium=90.0, lot_size=65, lots=1))
    parquet_journal.log_exit("ac1", 95.0, "TARGET_HIT", dt.datetime.now(dt.timezone.utc))
    row = parquet_journal.load_all().set_index("trade_id").loc["ac1"]
    assert row["exit_premium"] == 95.0
    assert row["pnl_gross"] is not None and not pd.isna(row["pnl_gross"])
    assert row["charges"] is not None and float(row["charges"]) > 0
    assert float(row["pnl_net"]) == float(row["pnl_gross"]) - float(row["charges"])


def test_update_trade_db_and_parquet_paths(parquet_journal, db_journal):
    parquet_journal.log_entry(make_record(trade_id="p1"))
    parquet_journal.update_trade("p1", {"current_sl": 88.0})
    db_journal.log_entry(make_record(trade_id="d1"))
    db_journal.update_trade("d1", {"current_sl": 77.0})
    assert float(parquet_journal.load_all().set_index("trade_id").loc["p1", "current_sl"]) == 88.0
    assert float(db_journal.load_all().set_index("trade_id").loc["d1", "current_sl"]) == 77.0
