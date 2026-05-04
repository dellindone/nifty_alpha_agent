from abc import ABC, abstractmethod
from enum import Enum


class TransactionType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"


class Segment(str, Enum):
    CASH = "CASH"
    FNO = "FNO"


class Product(str, Enum):
    MIS = "MIS"
    CNC = "CNC"
    NRML = "NRML"


class BrokerAdapter(ABC):
    @abstractmethod
    def place_order(self, symbol: str, qty: int, transaction_type: TransactionType, order_type: OrderType, segment: Segment, product: Product, price: float = 0.0) -> dict: ...
    @abstractmethod
    def cancel_order(self, order_id: str) -> dict: ...
    @abstractmethod
    def modify_order(self, order_id: str, qty: int = None, order_type: OrderType = None, price: float = None) -> dict: ...
    @abstractmethod
    def get_order_status(self, order_id: str, segment: Segment) -> str | None: ...
    @abstractmethod
    def get_order_executed_price(self, order_id: str, segment: Segment) -> float | None: ...
    @abstractmethod
    def get_positions(self) -> list[dict]: ...
