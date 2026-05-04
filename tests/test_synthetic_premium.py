import math

from ingestion.synthetic_premium import synthetic_premium


def test_synthetic_premium_math_properties():
    s, k, d, v, r = 22500, 22500, 7, 15.0, 6.5
    c_atm = synthetic_premium.compute(s, k, d, v, r, "CE")
    p_atm = synthetic_premium.compute(s, k, d, v, r, "PE")
    c_itm = synthetic_premium.compute(s, k - 500, d, v, r, "CE")
    c_otm = synthetic_premium.compute(s, k + 500, d, v, r, "CE")
    assert c_atm and c_atm > 0 and c_itm > c_atm > c_otm
    t = d / 365.0
    parity = s - k * math.exp(-(r / 100.0) * t)
    assert abs((c_atm - p_atm) - parity) < 5.0
    z1 = synthetic_premium.compute(s, k, 0, v, r, "CE")
    z2 = synthetic_premium.compute(s, k, d, 0, r, "CE")
    assert z1 is None or z1 >= 0.0
    assert z2 is None or z2 >= 0.0
    assert synthetic_premium.compute(s, k, d, 30.0, r, "CE") > c_atm
    assert synthetic_premium.compute(s, k, 30, v, r, "CE") > c_atm
