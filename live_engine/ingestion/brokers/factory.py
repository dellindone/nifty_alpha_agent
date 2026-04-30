from ingestion.brokers.base import AbstractBroker
from ingestion.brokers.dhan import DhanBroker
from ingestion.brokers.fyers import FyersBroker


class BrokerFactory:
    @staticmethod
    def get(broker: str) -> AbstractBroker:
        if broker == "fyers_primary":
            return FyersBroker("primary")
        if broker == "fyers_secondary":
            return FyersBroker("secondary")
        if broker == "dhan":
            return DhanBroker()
        raise ValueError(f"Unknown broker: {broker}")
