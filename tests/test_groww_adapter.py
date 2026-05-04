from brokers.base import OrderType, Product, Segment, TransactionType
from brokers.groww.adapter import GrowwAdapter


class FakeGroww:
    VALIDITY_DAY = "DAY"

    def __init__(self):
        self.last = None

    def place_order(self, **payload):
        self.last = payload
        return {"status": "SUCCESS", "groww_order_id": "G1"}

    def get_order_list(self, **_kwargs):
        return {"order_list": [{"groww_order_id": "G1", "order_status": "EXECUTED", "average_fill_price": 111.5}]}

    def cancel_order(self, **payload):
        return payload

    def modify_order(self, **payload):
        return payload

    def get_positions(self):
        return []


class BadGroww(FakeGroww):
    def place_order(self, **payload):
        self.last = payload
        return {"status": "ERROR"}


def test_symbol_transform():
    adapter = GrowwAdapter(client=FakeGroww())
    assert adapter._to_groww_symbol("NSE:NIFTY25JUN19000CE") == "NIFTY25JUN19000CE"
    assert adapter._to_groww_symbol("BSE:SENSEX25JUN80000CE") == "SENSEX25JUN80000CE"


def test_place_order_strips_prefix():
    api = FakeGroww()
    GrowwAdapter(client=api).place_order("NSE:NIFTY25JUN19000CE", 50, TransactionType.BUY, OrderType.MARKET, Segment.FNO, Product.NRML)
    assert api.last["trading_symbol"] == "NIFTY25JUN19000CE"


def test_place_order_raises_on_error():
    try:
        GrowwAdapter(client=BadGroww()).place_order("NSE:NIFTY25JUN19000CE", 1, TransactionType.BUY, OrderType.MARKET, Segment.FNO, Product.NRML)
        assert False
    except RuntimeError:
        assert True


def test_status_and_fill_price():
    api = FakeGroww()
    adapter = GrowwAdapter(client=api)
    assert adapter.get_order_status("G1", Segment.FNO) == "EXECUTED"
    assert adapter.get_order_executed_price("G1", Segment.FNO) == 111.5
    assert adapter.cancel_order("G1")["order_id"] == "G1"
    assert adapter.modify_order("G1", qty=2, order_type=OrderType.LIMIT, price=10)["groww_order_id"] == "G1"
    assert adapter.get_positions() == []
