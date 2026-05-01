from brokers.base import BrokerAdapter
from brokers.fyers.adapter import FyersAdapter
from brokers.groww.adapter import GrowwAdapter


class BrokerFactory:
    _registry: dict[str, type[BrokerAdapter]] = {}

    @classmethod
    def register(cls, name: str, creator) -> None:
        cls._registry[str(name).strip().lower()] = creator

    @classmethod
    def create(cls, name: str) -> BrokerAdapter:
        key = str(name).strip().lower()
        if key not in cls._registry:
            raise ValueError(f"Unknown broker: {name}")
        return cls._registry[key]()


BrokerFactory.register("fyers", FyersAdapter)
BrokerFactory.register("groww", GrowwAdapter)
