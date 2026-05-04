from brokers.groww.auth import GrowwAuth


class FakeGrowwAPI:
    @staticmethod
    def get_access_token(api_key, totp):
        return f"{api_key}:{totp}"

    def __init__(self, token):
        self.token = token


def test_groww_auth_refresh_and_cache(monkeypatch):
    monkeypatch.setattr("brokers.groww.auth.GrowwAPI", FakeGrowwAPI)
    monkeypatch.setattr("brokers.groww.auth.pyotp.TOTP", lambda secret: type("T", (), {"now": lambda self: "123456"})())
    monkeypatch.setenv("GROWW_API_KEY", "KEY")
    monkeypatch.setenv("GROWW_TOTP_SECRET", "ABC")
    auth = GrowwAuth()
    auth._client = None
    client = auth.refresh()
    assert client.token == "KEY:123456"
    assert auth.get_client() is client
