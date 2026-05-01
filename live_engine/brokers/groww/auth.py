import os

import pyotp

try:
    from growwapi import GrowwAPI
except ModuleNotFoundError:  # pragma: no cover
    GrowwAPI = None


class GrowwAuth:
    _instance = None
    _client = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def refresh(self):
        if GrowwAPI is None:
            raise ModuleNotFoundError("growwapi")
        secret = os.getenv("GROWW_TOTP_SECRET", "").strip().upper()
        secret += "=" * ((8 - len(secret) % 8) % 8)
        token = GrowwAPI.get_access_token(api_key=os.getenv("GROWW_API_KEY"), totp=pyotp.TOTP(secret).now())
        self._client = GrowwAPI(token)
        return self._client

    def get_client(self):
        return self._client or self.refresh()
