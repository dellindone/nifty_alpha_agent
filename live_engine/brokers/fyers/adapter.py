import logging
from collections.abc import Mapping, Sequence

from brokers.base import BrokerAdapter, OrderType, Product, Segment, TransactionType
from brokers.fyers.auth import FyersAuth

logger = logging.getLogger(__name__)

class FyersAdapter(BrokerAdapter):
    _TYPE_MAP = {OrderType.LIMIT: 1, OrderType.MARKET: 2, OrderType.SL_M: 3, OrderType.SL: 4}
    _PRODUCT_MAP = {Product.MIS: "INTRADAY", Product.NRML: "MARGIN", Product.CNC: "CNC"}
    _STATUS_MAP = {2: "FILLED", 1: "CANCELLED", 5: "REJECTED", 6: "PENDING", 4: "TRANSIT"}

    def __init__(self, model=None) -> None:
        self._model = model

    def _client(self):
        return self._model or FyersAuth().get_model()

    def place_order(self, symbol: str, qty: int, transaction_type: TransactionType, order_type: OrderType, segment: Segment, product: Product, price: float = 0.0) -> dict:
        payload = {"symbol": symbol, "qty": qty, "side": 1 if transaction_type == TransactionType.BUY else -1, "type": self._TYPE_MAP[order_type], "productType": self._PRODUCT_MAP[product], "validity": "DAY", "limitPrice": price if order_type in (OrderType.LIMIT, OrderType.SL) else 0, "stopPrice": price if order_type in (OrderType.SL_M, OrderType.SL) else 0, "disclosedQty": 0, "offlineOrder": False}
        response = self._client().place_order(payload)
        if response.get("s") != "ok":
            logger.error("broker place_order failed symbol=%s error=%s", symbol, response)
            raise RuntimeError(str(response))
        logger.info("broker place_order symbol=%s qty=%d order_id=%s", symbol, qty, response.get("id"))
        return {"order_id": response.get("id"), "raw": response}

    def cancel_order(self, order_id: str) -> dict:
        result = self._client().cancel_order({"id": order_id}); logger.info("broker cancel_order order_id=%s", order_id); return result

    def modify_order(self, order_id: str, qty: int = None, order_type: OrderType = None, price: float = None) -> dict:
        payload = {"id": order_id}
        if qty is not None:
            payload["qty"] = qty
        if order_type is not None:
            payload["type"] = self._TYPE_MAP[order_type]
        if price is not None:
            payload["limitPrice"] = price
        result = self._client().modify_order(payload); logger.info("broker modify_order order_id=%s", order_id); return result

    def get_order_status(self, order_id: str, segment: Segment) -> str | None:
        for order in self._client().orderbook().get("orderBook", []):
            if str(order.get("id")) == str(order_id):
                status = order.get("status")
                return self._STATUS_MAP.get(status, str(status) if status is not None else None)
        return None

    def get_order_executed_price(self, order_id: str, segment: Segment) -> float | None:
        for order in self._client().orderbook().get("orderBook", []):
            if str(order.get("id")) == str(order_id) and order.get("status") == 2:
                price = order.get("tradedPrice")
                return None if price in (None, "") else float(price)
        return None

    def get_positions(self) -> list[dict]:
        return self._client().positions().get("netPositions", [])

    def get_available_balance(self) -> float | None:
        response = self._client().funds()
        balance = self._extract_available_balance(response)
        logger.info("broker funds fyers available_balance=%s", balance)
        return balance

    def _extract_available_balance(self, payload) -> float | None:
        priority_keys = (
            "available_balance",
            "availableBalance",
            "availableFunds",
            "available_funds",
            "equityAmount",
            "equity_amount",
            "netAvailable",
            "net_available",
            "balance",
            "fund_balance",
            "fundBalance",
        )
        if isinstance(payload, Mapping):
            for key in priority_keys:
                if key in payload:
                    try:
                        return float(payload[key])
                    except (TypeError, ValueError):
                        pass
            for value in payload.values():
                found = self._extract_available_balance(value)
                if found is not None:
                    return found
        elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
            for item in payload:
                found = self._extract_available_balance(item)
                if found is not None:
                    return found
        return None
