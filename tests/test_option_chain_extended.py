import datetime as dt

import pandas as pd

from ingestion.option_chain import OptionChainService


def _df():
    return pd.DataFrame(
        {
            1: ["NIFTY 08 May 26 24150 CE", "NIFTY 08 May 26 24200 CE", "NIFTY 08 May 26 24250 PE", "NIFTY 08 May 26 24300 PE"],
            3: [65, 65, 65, 65],
            9: ["NSE:NIFTY08MAY2624150CE", "NSE:NIFTY08MAY2624200CE", "NSE:NIFTY08MAY2624250PE", "NSE:NIFTY08MAY2624300PE"],
            15: [24150, 24200, 24250, 24300],
        }
    )


def test_extract_select_filter_and_build_chain(monkeypatch):
    s = OptionChainService(); d = _df()
    e = s._extract_expiry_dates(d.copy()); assert e is not None and "date" in e.columns
    monkeypatch.setattr("ingestion.option_chain.date", type("D", (), {"today": staticmethod(lambda: dt.date(2026, 5, 4))}))
    exp, dd = s._select_expiry("NIFTY", e); assert exp is not None and dd > 0
    assert s._filter_scrip(d.copy(), "NIFTY") is not None
    monkeypatch.setattr("ingestion.option_chain.fyers_client.get_session", lambda: object())
    monkeypatch.setattr(s, "_fetch_ltp", lambda a, b: 24200.0)
    ch, atm, ltp = s._build_strike_chain(e.copy(), "NIFTY", "BULLISH")
    assert ch is not None and atm is not None and ltp == 24200.0


def test_fetch_ltp_quotes_process_and_best(monkeypatch):
    s = OptionChainService(); sess = type("S", (), {"quotes": lambda self, p: {"s": "ok", "d": [{"n": "NSE:NIFTY08MAY2624200CE", "v": {"lp": 90.5, "volume": 10, "bid": [[90.0]], "ask": [[91.0]]}}]}})()
    assert s._fetch_ltp("NIFTY", sess) == 90.5
    assert isinstance(s._fetch_quotes(["NSE:X"], sess), list)
    proc = s._process_quotes(_df(), sess, "NIFTY")
    assert proc and {"lp", "spread", "instrument"} <= set(proc[0])
    monkeypatch.setattr(s, "_fetch_csv", lambda x: _df())
    monkeypatch.setattr(s, "_extract_expiry_dates", lambda x: x.assign(date=pd.to_datetime(["2026-05-08"] * len(x))))
    monkeypatch.setattr(s, "_select_expiry", lambda a, b: (dt.date(2026, 5, 8), 4))
    monkeypatch.setattr("ingestion.option_chain.fyers_client.get_session", lambda: sess)
    monkeypatch.setattr(s, "_build_strike_chain", lambda a, b, c: (_df(), 24200, 24210))
    monkeypatch.setattr(s, "_process_quotes", lambda a, b, c: [{"instrument": "NIFTYCE", "lp": 90.0, "strike": 24200, "lot_size": 65, "volume": 1, "net_value": 5850, "spread": 0.01}])
    out = s.get_best_instrument("NIFTY", "BULLISH")
    assert out and out["atm"] == 24200
