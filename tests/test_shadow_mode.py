from datetime import date, datetime, timezone

import pytest
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.pool import StaticPool

import db
import lib.journal as jm
import risk.capital_tracker as cm
from lib.journal import Journal, TradeRecord
from lib.signal_handler import TradeSignal
from shadow_mode import ShadowMode
from risk.capital_tracker import CapitalTracker


def _upsert(engine, table, row):
    vals = {k: (None if pd.isna(v) else v) for k, v in row.items() if k in {c.name for c in table.columns}}
    stmt = sqlite_insert(table).values(**vals)
    with engine.begin() as c:
        c.execute(stmt.on_conflict_do_update(index_elements=[table.c.trade_id], set_={k: stmt.excluded[k] for k in row if k in table.c and k != "trade_id"}))


@pytest.fixture
def env(tmp_path, monkeypatch):
    eng = create_engine("sqlite+pysqlite:///:memory:", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("AGENT_MODE", "SHADOW")
    monkeypatch.setattr(db, "get_engine", lambda: eng)
    monkeypatch.setattr(cm, "get_engine", lambda: eng)
    monkeypatch.setattr(jm, "get_engine", lambda: eng)
    monkeypatch.setattr(jm, "_upsert_fn", lambda e, r: _upsert(e, db.paper_trade, r))
    monkeypatch.setattr(jm, "ensure_table_exists", lambda _e: db.metadata.create_all(eng, tables=[db.paper_trade], checkfirst=True))
    j = Journal(tmp_path)
    c = CapitalTracker(data_dir=tmp_path, initial_capital=100000)
    return j, c


def _sig(inst="NIFTY", entry=100, sl=20, tp=30, lots=1):
    return TradeSignal(inst, 1, "CE", 22400, date(2026, 5, 7), entry, sl, tp, "WIDE", "15m", 0.8, 0.7, 14.0, 20.0, 75, lots)


def test_enter_and_blocks_and_force_close_restore(env):
    j, c = env
    sm = ShadowMode(j, c)
    t = sm.enter_trade(_sig(), "NSE:NIFTY")
    assert t is not None and c.get_available_capital() < c.get_current_capital()
    assert sm.enter_trade(_sig(), "NSE:NIFTY") is None
    assert ShadowMode(j, CapitalTracker(data_dir=j.trades_path.parent, initial_capital=100000)).open_trades()
    assert sm.force_close_all({"NIFTY": 90.0}, "EOD")[0]["exit_reason"] == "EOD"


def test_enter_blocks_insufficient_capital(env):
    j, _ = env
    sm = ShadowMode(j, CapitalTracker(data_dir=j.trades_path.parent, initial_capital=100))
    assert sm.enter_trade(_sig(entry=500, lots=3), "NSE:NIFTY") is None


def test_tick_sl_target_trail_and_ratchet(env):
    j, c = env
    sm = ShadowMode(j, c)
    tr = sm.enter_trade(_sig(entry=100, sl=20, tp=30), "NSE:NIFTY")
    out = sm.tick("NIFTY", 79.0, datetime.now(timezone.utc))
    assert out and out[0]["exit_reason"] == "SL_HIT"
    sm.enter_trade(_sig(entry=100, sl=20, tp=30), "NSE:NIFTY")
    out = sm.tick("NIFTY", 131.0, datetime.now(timezone.utc))
    assert out and out[0]["exit_reason"] == "TARGET_HIT"
    tr = sm.enter_trade(_sig(entry=100, sl=20, tp=80), "NSE:NIFTY")
    sm.tick("NIFTY", 121.0, datetime.now(timezone.utc))
    t = sm.open_trades()[0]
    assert t.trail_active is True and t.current_sl >= 110.0
    sm.tick("NIFTY", 140.0, datetime.now(timezone.utc))
    hi = sm.open_trades()[0].current_sl
    sm.tick("NIFTY", 135.0, datetime.now(timezone.utc))
    lo = sm.open_trades()[0].current_sl
    assert lo == hi
    out = sm.tick("NIFTY", 129.0, datetime.now(timezone.utc))
    assert out and out[0]["exit_reason"] == "TRAIL_STOP"
