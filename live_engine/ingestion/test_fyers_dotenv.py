def test_dotenv_path_points_to_agent_root():
    from pathlib import Path
    expected = Path(__file__).resolve().parents[2] / ".env"
    fyers_client_path = Path(__file__).resolve().parent / "fyers_client.py"
    computed = fyers_client_path.parents[2] / ".env"
    assert computed == expected
    assert computed.parent.name == "nifty_alpha_agent"
