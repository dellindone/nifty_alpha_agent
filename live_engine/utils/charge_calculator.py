"""Trading charge estimation helpers."""

from utils.slippage_estimator import estimate_slippage
from config.settings import Equity


def calculate_charges(
    premium: float,
    lot_size: int,
    lots: int,
    instrument: str,
    side: str = "SELL",
) -> dict[str, float]:
    """Estimate execution charges for an options trade.

    Assumptions:
    - `premium` is per-unit option premium.
    - Brokerage is flat at Rs. 40 for the round trip.
    - Exchange charge is flat at Rs. 10.
    - STT and stamp duty are estimated using standard option-premium rates.
    - Slippage uses the instrument ATM profile unless modeled elsewhere.
    """
    quantity = max(lot_size, 0) * max(lots, 0)
    turnover = max(premium, 0.0) * quantity

    stt = round(turnover * Equity.STT_RATE, 2) if side.upper() == "SELL" else 0.0
    brokerage = Equity.BROKERAGE_PER_ORDER if quantity else 0.0
    exchange = Equity.EXCHANGE_CHARGE if quantity else 0.0
    gst = round((brokerage + exchange) * Equity.GST_RATE, 2)
    stamp_duty = round(turnover * Equity.STAMP_DUTY_RATE, 2)
    slippage = estimate_slippage(instrument=instrument, quantity=quantity)
    total = round(stt + brokerage + exchange + gst + stamp_duty + slippage, 2)

    return {
        "stt": stt,
        "brokerage": round(brokerage, 2),
        "exchange": round(exchange, 2),
        "gst": gst,
        "stamp_duty": stamp_duty,
        "slippage": slippage,
        "total": total,
    }
