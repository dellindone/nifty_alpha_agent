from abc import ABC, abstractmethod


class AbstractBroker(ABC):
    @abstractmethod
    def get_historical(self, symbol: str, resolution: str, date_from: str, date_to: str) -> list: ...

    @abstractmethod
    def get_quote(self, symbols: list[str]) -> list[dict]: ...
