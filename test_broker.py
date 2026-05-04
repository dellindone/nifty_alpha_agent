"""One-shot broker connectivity test — places 1 qty NIFTY CE order via configured broker, then exits.
Run: python test_broker.py
Cancel the order manually from your broker app.
"""
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
sys.path.insert(0, str(Path(__file__).parent / "live_engine"))

from config.settings import Trading
from config.instruments import LOT_SIZES
from brokers.factory import BrokerFactory
from brokers.base import OrderType, Product, Segment, TransactionType
from ingestion.option_chain import option_chain_service
from strategy.strike_selector import strike_selector
from ingestion.fyers_client import fyers_client

print(f"Broker: {Trading.BROKER_NAME}")

fyers_client.get_session()

chain = option_chain_service.get_best_instrument("NIFTY", "BULLISH")
if not chain or not chain.get("processed"):
    print("ERROR: could not fetch option chain")
    sys.exit(1)

selected = strike_selector.select(chain["processed"], chain.get("atm", 0), "BULLISH", instrument="NIFTY")
if not selected:
    print("ERROR: strike selector returned nothing")
    sys.exit(1)

instrument_name = str(selected.get("instrument", ""))
raw_symbol = f"NSE:{instrument_name}" if instrument_name else ""
strike = int(float(selected.get("strike", 0)))
ltp = float(selected.get("lp", 0))
print(f"Option: {raw_symbol}  strike={strike}  ltp={ltp}")
if not instrument_name:
    print("ERROR: no instrument symbol in selected strike")
    sys.exit(1)

lot_size = selected.get("lot_size") or LOT_SIZES.get("NIFTY", 65)
broker = BrokerFactory.create(Trading.BROKER_NAME)
groww_symbol = raw_symbol.split(":")[-1]
exchange = "BSE" if raw_symbol.upper().startswith("BSE:") else "NSE"
print(f"Sending → trading_symbol={groww_symbol}  exchange={exchange}  qty={lot_size}  segment=FNO  product=NRML  order_type=MARKET")
result = broker.place_order(
    symbol=raw_symbol,
    qty=lot_size,
    transaction_type=TransactionType.BUY,
    order_type=OrderType.MARKET,
    segment=Segment.FNO,
    product=Product.NRML,
)
print(f"Order placed: {result}")
print("Cancel this order from your broker app now.")
