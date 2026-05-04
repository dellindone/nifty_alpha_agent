import pytest

from brokers.base import OrderType, Product, Segment, TransactionType
from brokers.fyers.adapter import FyersAdapter


class FakeFyers:
    def __init__(self, status="ok"):
        self.status = status
        self.last = None

    def place_order(self, payload):
        self.last = payload
        return {"s": self.status, "id": "OID1"}

    def orderbook(self):
        return {"orderBook": [{"id": "OID1", "status": 2, "tradedPrice": 123.4}]}

    def cancel_order(self, payload):
        return payload

    def modify_order(self, payload):
        return payload

    def positions(self):
        return {"netPositions": []}


def test_place_order_maps_side_and_type():
    api = FakeFyers()
    adapter = FyersAdapter(model=api)
    adapter.place_order("NSE:NIFTY25JUN19000CE", 50, TransactionType.BUY, OrderType.MARKET, Segment.FNO, Product.NRML)
    assert api.last["side"] == 1 and api.last["type"] == 2 and api.last["productType"] == "MARGIN"
    adapter.place_order("NSE:NIFTY25JUN19000CE", 50, TransactionType.SELL, OrderType.LIMIT, Segment.FNO, Product.NRML, 101)
    assert api.last["side"] == -1 and api.last["type"] == 1 and api.last["symbol"] == "NSE:NIFTY25JUN19000CE"


def test_place_order_raises_on_error():
    with pytest.raises(RuntimeError):
        FyersAdapter(model=FakeFyers(status="error")).place_order("NSE:NIFTY25JUN19000CE", 1, TransactionType.BUY, OrderType.MARKET, Segment.FNO, Product.NRML)


def test_order_id_and_status_mapping():
    api = FakeFyers()
    adapter = FyersAdapter(model=api)
    assert adapter.place_order("NSE:NIFTY25JUN19000CE", 1, TransactionType.BUY, OrderType.MARKET, Segment.FNO, Product.NRML)["order_id"] == "OID1"
    assert adapter.get_order_status("OID1", Segment.FNO) == "FILLED"
    assert adapter.get_order_executed_price("OID1", Segment.FNO) == 123.4
    assert adapter.cancel_order("OID1") == {"id": "OID1"}
    assert adapter.modify_order("OID1", qty=2, order_type=OrderType.SL, price=99)["type"] == 4
    assert adapter.get_positions() == []
