from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from ingestion.fyers_client import FyersClient
from ingestion.option_chain import OptionChainService


def test_fyers_client_methods_and_singleton_session_reuse():
    c = FyersClient()
    c._session = c._login_time = None
    fake = MagicMock()
    fake.history.return_value = {"s": "ok", "candles": [[1, 2, 3, 4, 5, 6]]}
    fake.quotes.return_value = {"d": [{"v": {"lp": 123.4}}, {"v": {"lp": 99.0}}]}
    with patch("ingestion.fyers_client.requests.get"), patch("ingestion.fyers_client.requests.post"), patch.object(c, "_login", return_value=fake) as lg:
        assert c.get_historical("NSE:NIFTY50-INDEX", "5", "2026-05-01", "2026-05-04")
        assert c.get_ltp("NSE:NIFTY50-INDEX") == 123.4
        assert isinstance(c.get_quotes(["A", "B"]), list)
        c.get_session(); c.get_session(); assert lg.call_count == 1
    fake.history.return_value = {"s": "error"}
    assert c.get_historical("x", "5", "a", "b") == []
    fake.history.side_effect = Exception("boom")
    assert c.get_historical("x", "5", "a", "b") == []
    fake.quotes.side_effect = Exception("boom")
    assert c.get_ltp("x") is None and c.get_quotes(["x"]) == []


def test_option_chain_best_instrument_and_csv_cache_ttl():
    s = OptionChainService()
    csv = pd.DataFrame({1: ["NIFTY 30 Dec 30 CE", "NIFTY 30 Dec 30 PE"], 3: [75, 75], 9: ["NSE:NIFTY30DEC3022400CE", "NSE:NIFTY30DEC3022600PE"], 15: [22400, 22600]})
    with patch.object(s, "_fetch_csv", return_value=csv), patch.object(s, "_extract_expiry_dates", return_value=csv.assign(date=pd.to_datetime(["2030-12-30", "2030-12-30"]))), patch.object(s, "_select_expiry", return_value=(date(2030, 12, 30), 3)), patch("ingestion.option_chain.fyers_client.get_session", return_value=object()), patch.object(s, "_build_strike_chain", side_effect=[(csv[csv[9].str.endswith("CE")], 22500, 22510), (csv[csv[9].str.endswith("PE")], 22500, 22510)]), patch.object(s, "_process_quotes", side_effect=[[{"instrument": "XCE", "strike": 22400, "lp": 100.0, "volume": 1, "lot_size": 75, "net_value": 7500, "spread": 0.01}], [{"instrument": "XPE", "strike": 22600, "lp": 101.0, "volume": 1, "lot_size": 75, "net_value": 7575, "spread": 0.01}]]):
        bull = s.get_best_instrument("NIFTY", "BULLISH")
        bear = s.get_best_instrument("NIFTY", "BEARISH")
    assert bull and {"processed", "atm", "expiry"} <= set(bull)
    assert bull["processed"][0]["instrument"].endswith("CE") and bear["processed"][0]["instrument"].endswith("PE")
    with patch.object(s, "_fetch_csv", return_value=None):
        assert s.get_best_instrument("NIFTY", "BULLISH") is None
    s._csv_cache.clear()
    good = "x,NIFTY 30 Dec 30 CE,x,75,x,x,x,x,x,NSE:NIFTY30DEC3022400CE,x,x,x,x,x,22400,x,x,x,x,x\n"
    resp = MagicMock(); resp.content = good.encode()
    with patch("ingestion.option_chain.requests.get", return_value=resp) as g, patch("ingestion.option_chain.time.time", return_value=100):
        s._fetch_csv("NIFTY"); s._fetch_csv("NIFTY")
    assert g.call_count == 1
