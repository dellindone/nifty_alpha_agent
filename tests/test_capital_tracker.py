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
