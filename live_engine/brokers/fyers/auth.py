from fyers_apiv3 import fyersModel

from ingestion.fyers_client import fyers_client


class FyersAuth:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_model(self) -> fyersModel.FyersModel:
        return fyers_client.get_session()
