from datetime import date, datetime, timezone

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.pool import StaticPool

import db
import lib.journal as jm
import risk.capital_tracker as cm
from lib.journal import Journal, TradeRecord
from lib.reporter import Reporter
from lib.signal_handler import TradeSignal
from risk.capital_tracker import CapitalTracker


def _upsert(engine, row):
    t = db.paper_trade
    normalized = db._normalize_record(row)
    vals = {k: (None if pd.isna(v) else v) for k, v in normalized.items() if k in {c.name for c in t.columns}}
    stmt = sqlite_insert(t).values(**vals)
    with engine.begin() as c:
        c.execute(stmt.on_conflict_do_update(index_elements=[t.c.trade_id], set_={k: stmt.excluded[k] for k in vals if k != "trade_id"}))


@pytest.fixture
def rep(tmp_path, monkeypatch):
    eng = create_engine("sqlite+pysqlite:///:memory:", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setenv("AGENT_MODE", "SHADOW")
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(jm, "get_engine", lambda: eng)
    monkeypatch.setattr(cm, "get_engine", lambda: eng)
    db.metadata.create_all(eng, tables=[db.paper_trade], checkfirst=True)
    monkeypatch.setattr(jm, "upsert_trade", lambda e, r: _upsert(e, r))
    return Reporter(Journal(tmp_path), CapitalTracker(data_dir=tmp_path, initial_capital=100000))


def test_reporter_messages(rep, monkeypatch):
    out = []
    monkeypatch.setattr("base.reporter.BaseReporter._send", lambda self, m, retries=3: out.append(m))
    s = TradeSignal("NIFTY", 1, "CE", 22400, date(2026, 5, 7), 100, 20, 30, "WIDE", "15m", 0.8, 0.7, 14, 20, 75, 1)
    rep.send_signal_alert(s)
    s.block_reason = "MAX_TRADES"
    rep.send_signal_alert(s, blocked=True)
    r1 = TradeRecord("t1", "NIFTY", datetime.now(timezone.utc), datetime.now(timezone.utc), 1, 22400, date(2026, 5, 7), "CE", 100, 120, 75, 1, 20, 30, "WIDE", "15m", 0.8, 0.7, "TARGET_HIT", 1500, 1400, 100, 14, 20, "v1")
    r2 = TradeRecord("t2", "NIFTY", datetime.now(timezone.utc), datetime.now(timezone.utc), 1, 22400, date(2026, 5, 7), "CE", 100, 90, 75, 1, 20, 30, "WIDE", "15m", 0.8, 0.7, "SL_HIT", -750, -820, 70, 14, 20, "v1")
    rep.send_exit_alert(r1)
    rep.send_exit_alert(r2)
    assert "22400" in out[0] and "Confidence" in out[0] and "VIX" in out[0]
    assert "NOT PUNCHED" in out[1] and "MAX_TRADES" in out[1]
    assert "✅" in out[2] and "TARGET_HIT" in out[2]
    assert "🔴" in out[3]


def test_reporter_daily_and_target(rep, monkeypatch):
    out = []
    monkeypatch.setattr("base.reporter.BaseReporter._send", lambda self, m, retries=3: out.append(m))
    rep.send_daily_summary()
    r1 = TradeRecord("t1", "NIFTY", datetime.now(timezone.utc), datetime.now(timezone.utc), 1, 22400, date(2026, 5, 7), "CE", 100, 120, 75, 1, 20, 30, "WIDE", "15m", 0.8, 0.7, "TARGET_HIT", 1500, 1400, 100, 14, 20, "v1")
    r2 = TradeRecord("t2", "NIFTY", datetime.now(timezone.utc), datetime.now(timezone.utc), 1, 22400, date(2026, 5, 7), "CE", 100, 90, 75, 1, 20, 30, "WIDE", "15m", 0.8, 0.7, "SL_HIT", -750, -820, 70, 14, 20, "v1")
    rep.journal.log_entry(r1)
    rep.journal.log_entry(r2)
    rep.send_daily_summary()
    rep.send_daily_target_alert(5123)
    assert "Trades: 0" in out[0]
    assert "Wins: 1" in out[1] and "Net:" in out[1]
    assert "5,123" in out[2]


def test_reporter_startup_summary(rep, monkeypatch):
    out = []
    monkeypatch.setattr("base.reporter.BaseReporter._send", lambda self, m, retries=3: out.append(m))

    started = datetime.now(timezone.utc)
    rep.send_startup_summary("NIFTY", started, [])

    closed = TradeRecord(
        "t3", "NIFTY", datetime.now(timezone.utc), datetime.now(timezone.utc), 0, 24200, date(2026, 5, 8), "PE",
        90, 105, 75, 1, 20, 30, "WIDE", "15m", 0.62, 0.38, "TARGET_HIT", 975, 900, 75, 18, 12, "v6"
    )
    cleanup = TradeRecord(
        "t4", "NIFTY", datetime.now(timezone.utc), datetime.now(timezone.utc), 1, 24300, date(2026, 5, 8), "CE",
        100, 95, 75, 1, 20, 30, "WIDE", "15m", 0.58, 0.42, "MANUAL_CLEANUP", -375, -450, 75, 18, 12, "v6"
    )
    rep.journal.log_entry(closed)
    rep.journal.log_entry(cleanup)
    open_trades = [{
        "instrument": "NIFTY", "expiry_date": date(2026, 5, 8), "strike": 24100, "option_type": "PE", "entry_premium": 88.0,
        "current_sl": 74.0, "target_price": 120.0, "lots": 2, "confidence": 0.67, "trail_active": True,
    }]
    rep.send_startup_summary("NIFTY", started, open_trades)

    assert len(out) == 2
    assert "AGENT RESTARTED" in out[0] and "NIFTY" in out[0] and "No open trades" in out[0]
    assert "TODAY'S PERFORMANCE" in out[1]
    assert "TARGET_HIT" in out[1]
    assert "MANUAL_CLEANUP" not in out[1]
    assert "OPEN TRADE(S) RESTORED" in out[1]
    assert "trailing" in out[1]
    assert "Capital:" in out[1]


def test_reporter_health_alert(rep, monkeypatch):
    out = []
    monkeypatch.setattr("base.reporter.BaseReporter._send", lambda self, m, retries=3: out.append(m))
    rep.send_health_alert("DB connection lost")
    assert out and "DB connection lost" in out[-1]


def test_reporter_restored_trades_alert(rep, monkeypatch):
    out = []
    monkeypatch.setattr("base.reporter.BaseReporter._send", lambda self, m, retries=3: out.append(m))
    trades = [
        {"option_type": "PE", "strike": 24100, "expiry_date": "2026-05-08", "entry_premium": 88.0, "current_sl": 74.0},
        {"option_type": "CE", "strike": 24300, "expiry_date": "2026-05-08", "entry_premium": 92.0, "current_sl": 70.0},
    ]
    rep.send_restored_trades_alert(trades)
    assert len(out) == 1
    msg = out[0]
    assert "OPEN TRADE(S) RESTORED" in msg
    assert "PE 24100" in msg and "CE 24300" in msg
    assert "entry:₹88" in msg and "SL:₹74" in msg
