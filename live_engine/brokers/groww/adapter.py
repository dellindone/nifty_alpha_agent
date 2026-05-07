import logging
from collections.abc import Mapping, Sequence

from brokers.base import BrokerAdapter, OrderType, Product, Segment, TransactionType
from brokers.groww.auth import GrowwAuth

logger = logging.getLogger(__name__)

class GrowwAdapter(BrokerAdapter):
    _FILLED = {"EXECUTED", "COMPLETED"}
    _FAILED = {"REJECTED", "FAILED", "CANCELLED"}

    def __init__(self, client=None) -> None:
        self._client = client

    def _api(self):
        return self._client or GrowwAuth().get_client()

    def _to_groww_symbol(self, symbol: str) -> str:
        return symbol.split(":")[-1]

    def _exchange(self, symbol: str) -> str:
        raw = self._to_groww_symbol(symbol).upper()
        return "BSE" if str(symbol).upper().startswith("BSE:") or raw.startswith("SENSEX") else "NSE"

    def place_order(self, symbol: str, qty: int, transaction_type: TransactionType, order_type: OrderType, segment: Segment, product: Product, price: float = 0.0) -> dict:
        response = self._api().place_order(trading_symbol=self._to_groww_symbol(symbol), quantity=qty, validity=self._api().VALIDITY_DAY, exchange=self._exchange(symbol), segment=segment.value, product=product.value, order_type=order_type.value, transaction_type=transaction_type.value, price=price)
        order_id = response.get("groww_order_id")
        order_status = str(response.get("order_status", "")).upper()
        if not order_id or order_status in self._FAILED:
            logger.error("broker place_order failed symbol=%s error=%s", symbol, response)
            raise RuntimeError(f"Groww place_order failed for {symbol}: {response}")
        logger.info("broker place_order symbol=%s qty=%d order_id=%s status=%s", symbol, qty, order_id, order_status)
        return {"order_id": order_id, "raw": response}

    def cancel_order(self, order_id: str) -> dict:
        result = self._api().cancel_order(order_id=order_id); logger.info("broker cancel_order order_id=%s", order_id); return result

    def modify_order(self, order_id: str, qty: int = None, order_type: OrderType = None, price: float = None) -> dict:
        result = self._api().modify_order(groww_order_id=order_id, quantity=qty, order_type=order_type.value if order_type else None, price=price); logger.info("broker modify_order order_id=%s", order_id); return result

    def get_order_status(self, order_id: str, segment: Segment) -> str | None:
        for order in self._api().get_order_list(page_size=50).get("order_list", []):
            if str(order.get("groww_order_id")) == str(order_id):
                return order.get("order_status")
        return None

    def get_order_executed_price(self, order_id: str, segment: Segment) -> float | None:
        for order in self._api().get_order_list(page_size=50).get("order_list", []):
            if str(order.get("groww_order_id")) == str(order_id) and str(order.get("order_status")) in self._FILLED:
                price = order.get("average_fill_price")
                return None if price in (None, "") else float(price)
        return None

    def get_positions(self) -> list[dict]:
        return self._api().get_positions()

    def get_available_balance(self) -> float | None:
        api = self._api()
        for method_name in ("get_fund_limits", "get_funds", "get_balance", "get_available_balance", "funds", "balance"):
            method = getattr(api, method_name, None)
            if callable(method):
                try:
                    response = method()
                except Exception as exc:
                    logger.warning("broker %s failed while reading funds: %s", method_name, exc)
                    continue
                balance = self._extract_available_balance(response)
                if balance is not None:
                    logger.info("broker funds groww available_balance=%s via %s", balance, method_name)
                    return balance
        logger.warning("broker funds groww unavailable from client")
        return None

    def _extract_available_balance(self, payload) -> float | None:
        priority_keys = (
            "available_balance",
            "availableBalance",
            "availableFunds",
            "available_funds",
            "available_cash",
            "availableCash",
            "withdrawable_balance",
            "withdrawableBalance",
            "clearCash",
            "clear_cash",
            "balance",
            "cash",
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
