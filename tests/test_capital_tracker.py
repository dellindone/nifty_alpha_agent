from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import create_engine

import risk.capital_tracker as ct


def test_capital_tracker_db_first_ignores_old_parquet(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    monkeypatch.setattr(ct, "get_engine", lambda: engine)
    old = pd.DataFrame([{"timestamp": datetime.now(timezone.utc), "capital": 100000.0, "daily_pnl": 0.0, "cumulative_pnl": 0.0, "open_margin_used": 0.0, "event": "INIT"}])
    old.to_parquet(tmp_path / "capital.parquet", index=False, engine="pyarrow")
    tracker = ct.CapitalTracker(data_dir=tmp_path, initial_capital=24000)
    assert tracker.current_capital == 24000.0


def test_capital_tracker_restores_from_db(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    monkeypatch.setattr(ct, "get_engine", lambda: engine)
    tracker = ct.CapitalTracker(data_dir=tmp_path, initial_capital=24000)
    tracker.apply_realized_pnl(1000.0)
    restored = ct.CapitalTracker(data_dir=tmp_path, initial_capital=24000)
    assert restored.current_capital == 25000.0


def test_reserve_and_release_margin(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    monkeypatch.setattr(ct, "get_engine", lambda: engine)
    tracker = ct.CapitalTracker(data_dir=tmp_path, initial_capital=100000)
    initial_available = tracker.get_available_capital()
    reserved = tracker.reserve_margin("trade_1", 5000.0)
    assert reserved is True
    assert tracker.get_available_capital() == initial_available - 5000.0
    tracker.release_margin("trade_1", 500.0)
    assert tracker.get_available_capital() == initial_available + 500.0


def test_reserve_blocks_when_insufficient(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    monkeypatch.setattr(ct, "get_engine", lambda: engine)
    tracker = ct.CapitalTracker(data_dir=tmp_path, initial_capital=1000)
    result = tracker.reserve_margin("t1", 999999.0)
    assert result is False
    assert tracker.get_available_capital() == tracker.get_current_capital()


def test_apply_realized_pnl(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    monkeypatch.setattr(ct, "get_engine", lambda: engine)
    tracker = ct.CapitalTracker(data_dir=tmp_path, initial_capital=50000)
    tracker.apply_realized_pnl(2000.0)
    assert tracker.get_current_capital() == 52000.0
    tracker.apply_realized_pnl(-1000.0)
    assert tracker.get_current_capital() == 51000.0


def test_snapshot_keys(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    monkeypatch.setattr(ct, "get_engine", lambda: engine)
    tracker = ct.CapitalTracker(data_dir=tmp_path, initial_capital=100000)
    tracker.snapshot(event="TEST")
    snap = tracker.load_history().iloc[-1].to_dict()
    assert isinstance(snap, dict)
    for key in ("capital", "daily_pnl", "cumulative_pnl", "open_margin_used"):
        assert key in snap


def test_capital_tracker_parquet_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "get_engine", lambda: None)
    tracker = ct.CapitalTracker(data_dir=tmp_path, initial_capital=80000)
    tracker.apply_realized_pnl(3000.0)
    tracker2 = ct.CapitalTracker(data_dir=tmp_path, initial_capital=80000)
    assert tracker2.get_current_capital() == 83000.0


def test_capital_tracker_parquet_fallback_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "get_engine", lambda: None)
    tracker = ct.CapitalTracker(data_dir=tmp_path, initial_capital=50000)
    assert tracker.get_current_capital() == 50000.0


def test_capital_tracker_load_parquet_fallback_read_error(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "get_engine", lambda: None)
    path = tmp_path / "capital.parquet"
    pd.DataFrame([{"timestamp": datetime.now(timezone.utc), "capital": 81000.0, "cumulative_pnl": 31000.0}]).to_parquet(path, index=False, engine="pyarrow")
    calls = {"n": 0}

    def fake_read_parquet(*args, **kwargs):
        calls["n"] += 1
        if kwargs.get("engine") == "pyarrow":
            raise RuntimeError("pyarrow read failed")
        return pd.DataFrame([{"timestamp": datetime.now(timezone.utc), "capital": 81000.0, "cumulative_pnl": 31000.0}])

    monkeypatch.setattr(ct.pd, "read_parquet", fake_read_parquet)
    tracker = ct.CapitalTracker(data_dir=tmp_path, initial_capital=50000)
    assert tracker.get_current_capital() == 81000.0
    assert calls["n"] >= 2
