from config.settings import get_instrument_config
from risk.position_sizer import PositionSizer, _clamp_sl, should_block_new_trades, widened_stop_loss


def test_get_lots_and_margin_required():
    s = PositionSizer(shadow_mode=False)
    lots = s.get_lots(capital=100000, sl_per_unit=90, lot_size=65, vix=15)
    assert isinstance(lots, int) and lots >= 1
    lots2 = s.get_lots(capital=100000, sl_per_unit=1e9, lot_size=65, vix=15)
    assert lots2 in {0, 1}
    assert s.get_margin_required(90, 65, 1) > 0


def test_should_block_and_widen_and_clamp():
    cfg = get_instrument_config("NIFTY")
    assert should_block_new_trades(31.0) is True
    assert should_block_new_trades(20.0) is False
    assert widened_stop_loss(20.0, 0.10) > 20.0
    assert widened_stop_loss(20.0, 0.01) == 20.0
    assert _clamp_sl(0.1) >= cfg.abs_sl_min
