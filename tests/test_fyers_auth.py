from brokers.fyers.auth import FyersAuth


def test_fyers_auth_singleton_and_session(monkeypatch):
    fake = object()
    monkeypatch.setattr("brokers.fyers.auth.fyers_client.get_session", lambda: fake)
    assert FyersAuth() is FyersAuth()
    assert FyersAuth().get_model() is fake
