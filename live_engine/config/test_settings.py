def test_paths_root_is_agent_dir():
    from config.settings import Paths
    assert Paths.ROOT.name == "nifty_alpha_agent", f"Expected nifty_alpha_agent, got {Paths.ROOT.name}"


def test_no_btc_in_data_dirs():
    from config.settings import Paths
    assert "btc" not in Paths.DATA_DIRS


def test_nifty_in_data_dirs():
    from config.settings import Paths
    assert "nifty" in Paths.DATA_DIRS


def test_nifty_instrument_config():
    from config.settings import INSTRUMENT_CONFIGS
    assert "NIFTY" in INSTRUMENT_CONFIGS
    assert "BANKNIFTY" not in INSTRUMENT_CONFIGS
    assert "SENSEX" not in INSTRUMENT_CONFIGS
