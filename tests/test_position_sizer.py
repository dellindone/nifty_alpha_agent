from config.settings import get_instrument_config
from risk.position_sizer import stop_loss_from_bin


def test_stop_loss_bins_monotonic_and_clamps():
    cfg = get_instrument_config("NIFTY")
    vals = {b: stop_loss_from_bin(b, 20, 14, cfg=cfg) for b in ["TIGHT", "NARROW", "MEDIUM", "WIDE", "VERY_WIDE"]}
    assert vals["TIGHT"] <= vals["NARROW"] <= vals["MEDIUM"] <= vals["WIDE"] <= vals["VERY_WIDE"]
    assert all(cfg.abs_sl_min <= v <= cfg.abs_sl_max for v in vals.values())
    assert stop_loss_from_bin("MEDIUM", 20, 30, cfg=cfg) >= stop_loss_from_bin("MEDIUM", 20, 14, cfg=cfg)
    assert stop_loss_from_bin("MEDIUM", 30, 14, cfg=cfg) >= stop_loss_from_bin("MEDIUM", 20, 14, cfg=cfg)
    assert stop_loss_from_bin("TIGHT", 0.001, 14, cfg=cfg) == cfg.abs_sl_min
    assert stop_loss_from_bin("VERY_WIDE", 100000, 14, cfg=cfg) == cfg.abs_sl_max
