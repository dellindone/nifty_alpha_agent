from datetime import date

from utils.market_calendar import days_to_next_expiry, is_trading_day, next_expiry


def test_market_calendar_basics_and_expiry_rules():
    assert is_trading_day(date(2026, 5, 2)) is False
    assert is_trading_day(date(2026, 5, 1)) is False
    assert is_trading_day(date(2026, 5, 5)) is True
    n = next_expiry("NIFTY", date(2026, 5, 4))
    b = next_expiry("BANKNIFTY", date(2026, 5, 4))
    assert n.weekday() == 1 and n >= date(2026, 5, 4)
    assert b.weekday() == 1 and b >= date(2026, 5, 4)
    d1 = days_to_next_expiry("NIFTY", n)
    d2 = days_to_next_expiry("NIFTY", date(2026, 5, 4))
    assert d2 >= 1 and d1 == 0
