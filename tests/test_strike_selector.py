from strategy.strike_selector import strike_selector


def _chain(atm, step):
    out = []
    for st in [atm - 4 * step, atm - 2 * step, atm, atm + 2 * step, atm + 4 * step]:
        out.append({"instrument": f"X{st}CE", "strike": st, "spread": 0.01, "lp": 100.0})
        out.append({"instrument": f"X{st}PE", "strike": st, "spread": 0.01, "lp": 100.0})
    return out


def test_strike_selector_modes_and_steps():
    n = _chain(22500, 50)
    ce = strike_selector.select([x for x in n if x["instrument"].endswith("CE")], 22500, "BULLISH", instrument="NIFTY")
    pe = strike_selector.select([x for x in n if x["instrument"].endswith("PE")], 22500, "BEARISH", instrument="NIFTY")
    assert ce and ce["strike"] == 22300 and ce["lp"] > 0
    assert pe and pe["strike"] == 22700
    assert strike_selector.select([], 22500, "BULLISH", instrument="NIFTY") is None
    fb = strike_selector.select([{"instrument": "X", "strike": 22500, "spread": 0.01, "lp": 1.0}], 22500, "BULLISH", instrument="NIFTY")
    assert fb and fb["instrument"] == "X"
    b = _chain(50000, 100)
    ce_b = strike_selector.select([x for x in b if x["instrument"].endswith("CE")], 50000, "BULLISH", instrument="BANKNIFTY")
    pe_b = strike_selector.select([x for x in b if x["instrument"].endswith("PE")], 50000, "BEARISH", instrument="BANKNIFTY")
    assert ce_b["strike"] == 49600 and pe_b["strike"] == 50400
