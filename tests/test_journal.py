from datetime import date, datetime, timezone

import pytest
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.pool import StaticPool

import db
import lib.journal as jm
from lib.journal import Journal, TradeRecord


def _upsert(engine, row):
    t = db.paper_trade
    vals = {k: (None if pd.isna(v) else v) for k, v in row.items() if k in {c.name for c in t.columns}}
    stmt = sqlite_insert(t).values(**vals)
    with engine.begin() as c:
        c.execute(stmt.on_conflict_do_update(index_elements=[t.c.trade_id], set_={k: stmt.excluded[k] for k in row if k in t.c and k != "trade_id"}))


@pytest.fixture
def journal(tmp_path, monkeypatch):
    eng = create_engine("sqlite+pysqlite:///:memory:", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setenv("AGENT_MODE", "SHADOW")
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(jm, "get_engine", lambda: eng)
    monkeypatch.setattr(jm, "ensure_table_exists", lambda _e: db.metadata.create_all(eng, tables=[db.paper_trade], checkfirst=True))
    monkeypatch.setattr(jm, "_upsert_fn", lambda e, r: _upsert(e, r))
    return Journal(tmp_path)


def _rec(tid, ts):
    return TradeRecord(tid, "NIFTY", ts, None, 1, 22400, date(2026, 5, 7), "CE", 100.0, None, 75, 1, 20.0, 30.0,
                       "WIDE", "15m", 0.8, 0.7, None, None, None, None, 14.0, 20.0, "v1")


def test_journal_entry_exit_open_state_and_updates(journal):
    t1 = datetime(2026, 5, 4, 4, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 5, 5, 4, 0, tzinfo=timezone.utc)
    journal.log_entry(_rec("t1", t1)); journal.log_entry(_rec("t2", t2))
    all_df = journal.load_all()
    assert {"t1", "t2"} == set(all_df.trade_id.astype(str))
    assert set(journal.load_open_trades().trade_id.astype(str)) == {"t1", "t2"}
    journal.update_trade_state("t1", current_sl=95.0, highest_premium=130.0, trail_active=True)
    one = journal.load_all().set_index("trade_id").loc["t1"]
    assert float(one.current_sl) == 95.0 and float(one.highest_premium) == 130.0 and bool(one.trail_active) is True
    journal.log_exit("t1", 125.0, "TARGET_HIT", datetime(2026, 5, 4, 5, 0, tzinfo=timezone.utc), pnl_gross=1875.0, pnl_net=1800.0, charges=75.0)
    row = journal.load_all().set_index("trade_id").loc["t1"]
    assert float(row.exit_premium) == 125.0 and row.exit_reason == "TARGET_HIT" and float(row.pnl_net) == 1800.0
    assert row.timestamp_exit is not None and set(journal.open_trades().trade_id.astype(str)) == {"t2"}
