import base64
import logging
import math
import os
import ssl
import threading
import time
from typing import Callable
from urllib.parse import parse_qs, urlparse

import certifi
import pyotp
import requests
from dotenv import load_dotenv
from fyers_apiv3 import fyersModel
from config.settings import Equity
try:
    from fyers_apiv3.FyersWebsocket.data_ws import FyersDataSocket as _FyersDataSocket
except Exception:
    _FyersDataSocket = None

load_dotenv()

# Point SSL at certifi's bundle — fixes macOS missing system cert.pem
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

logger = logging.getLogger(__name__)


class FyersClient:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._session = None
            cls._instance._login_time = None
            cls._instance._access_token = None
            cls._instance._client_id = None
        return cls._instance

    def _is_token_expired(self) -> bool:
        if self._login_time is None:
            return True
        return (time.time() - self._login_time) > Equity.TOKEN_MAX_AGE_SECONDS

    def get_session(self):
        if self._session is None or self._is_token_expired():
            logger.info("Fyers session missing or expired, logging in...")
            self._session = self._login()
            self._login_time = time.time() if self._session else None
        return self._session

    def get_ws_access_token(self) -> str:
        """Return 'client_id:access_token' string required by FyersDataSocket."""
        if self._client_id and self._access_token:
            return f"{self._client_id}:{self._access_token}"
        return ""

    def invalidate(self):
        self._session = None
        self._login_time = None
        self._access_token = None

    def get_historical(self, symbol: str, resolution: str, date_from: str, date_to: str) -> list:
        """Fetch OHLCV bars. resolution = '1', '5', '15', '60', 'D'. Returns list of dicts."""
        session = self.get_session()
        if not session:
            return []
        try:
            data = session.history(
                {
                    "symbol": symbol,
                    "resolution": resolution,
                    "date_format": "1",
                    "range_from": date_from,
                    "range_to": date_to,
                    "cont_flag": "1",
                }
            )
            if data.get("s") != "ok":
                logger.error(f"History fetch failed for {symbol}: {data}")
                return []
            return data.get("candles", [])
        except Exception as e:
            logger.error(f"get_historical error: {e}")
            return []

    def get_quotes(self, symbols: list) -> list:
        """Fetch live quotes for a list of Fyers symbol strings. Returns raw 'd' list."""
        session = self.get_session()
        if not session:
            return []
        try:
            data = session.quotes({"symbols": ",".join(symbols)})
            if self._is_auth_error(data):
                self.invalidate()
                session = self.get_session()
                if not session:
                    return []
                data = session.quotes({"symbols": ",".join(symbols)})
            return data.get("d", [])
        except Exception as e:
            logger.error(f"get_quotes error: {e}")
            return []

    def get_ltp(self, fyers_symbol: str) -> float | None:
        """Return current last traded price for a single Fyers symbol string."""
        quotes = self.get_quotes([fyers_symbol])
        if not quotes:
            return None
        return quotes[0]["v"]["lp"]

    def get_vix(self) -> float | None:
        """Return current India VIX value."""
        return self.get_ltp("NSE:INDIAVIX-INDEX")

    def _is_auth_error(self, response: dict) -> bool:
        code = response.get("code", 0)
        message = str(response.get("message", "")).lower()
        return response.get("s") == "error" and (
            code in (-16, -14, 10, 16) or "token" in message or "auth" in message or "session" in message
        )

    def _get_encoded(self, value: str) -> str:
        return base64.b64encode(value.encode("ascii")).decode("ascii")

    def _login(self):
        try:
            fy_id = os.getenv("FYERS_ID")
            client_id = os.getenv("FYERS_CLIENT_ID")
            secret_key = os.getenv("FYERS_SECRET_KEY")
            redirect_uri = os.getenv("FYERS_REDIRECT_URI")
            totp_secret = os.getenv("FYERS_TOTP_SECRET")
            pin = os.getenv("FYERS_PIN")

            res = requests.post(
                "https://api-t2.fyers.in/vagator/v2/send_login_otp_v2",
                json={"fy_id": self._get_encoded(fy_id), "app_id": "2"},
            ).json()
            if res.get("s") != "ok":
                logger.error(f"OTP send failed: {res}")
                return None
            request_key = res["request_key"]

            if time.localtime().tm_sec % 30 > 27:
                time.sleep(5)
            totp = pyotp.TOTP(totp_secret).now()
            res = requests.post(
                "https://api-t2.fyers.in/vagator/v2/verify_otp",
                json={"request_key": request_key, "otp": totp},
            ).json()
            if res.get("s") != "ok":
                logger.error(f"OTP verify failed: {res}")
                return None
            request_key = res["request_key"]

            ses = requests.Session()
            res = ses.post(
                "https://api-t2.fyers.in/vagator/v2/verify_pin_v2",
                json={
                    "request_key": request_key,
                    "identity_type": "pin",
                    "identifier": self._get_encoded(pin),
                },
            ).json()
            if res.get("s") != "ok":
                logger.error(f"PIN verify failed: {res}")
                return None
            ses.headers.update({"authorization": f"Bearer {res['data']['access_token']}"})

            res = ses.post(
                "https://api-t1.fyers.in/api/v3/token",
                json={
                    "fyers_id": fy_id,
                    "app_id": client_id[:-4],
                    "redirect_uri": redirect_uri,
                    "appType": "100",
                    "response_type": "code",
                    "create_cookie": True,
                },
            ).json()
            if res.get("s") != "ok":
                logger.error(f"Auth code failed: {res}")
                return None
            auth_code = parse_qs(urlparse(res["Url"]).query).get("auth_code", [None])[0]

            sess = fyersModel.SessionModel(
                client_id=client_id,
                secret_key=secret_key,
                redirect_uri=redirect_uri,
                response_type="code",
                grant_type="authorization_code",
            )
            sess.set_token(auth_code)
            token_resp = sess.generate_token()
            if not token_resp or not token_resp.get("access_token"):
                logger.error(f"Token exchange failed: {token_resp}")
                return None

            fyers_obj = fyersModel.FyersModel(
                client_id=client_id,
                token=token_resp["access_token"],
                is_async=False,
                log_path="",
            )
            self._access_token = token_resp["access_token"]
            self._client_id = client_id
            logger.info("Fyers login successful")
            return fyers_obj
        except Exception as e:
            logger.error(f"Fyers login exception: {e}")
            return None


fyers_client = FyersClient()


class FyersTickStream:
    def __init__(self, access_token_getter: Callable[[], str]) -> None:
        self._access_token_getter = access_token_getter
        self._socket = None
        self._lock = threading.Lock()
        self._running = False
        self._intentional_stop = False
        self._reconnect_attempts = 0
        self._reconnect_scheduled = False
        self._max_reconnect_attempts = 10
        self._connect_thread: threading.Thread | None = None
        self._on_tick: Callable[[str, float], None] | None = None
        self._subscribed_symbols: set[str] = set()

    def start(self, on_tick: Callable[[str, float], None]) -> None:
        with self._lock:
            self._on_tick = on_tick
            self._running = True
            self._intentional_stop = False
            if self._connect_thread is not None and self._connect_thread.is_alive():
                return
            self._connect_thread = threading.Thread(target=self._connect_socket, daemon=True)
            self._connect_thread.start()

    def subscribe(self, symbols: list[str]) -> None:
        normalized = [str(symbol).upper() for symbol in symbols if str(symbol).strip()]
        if not normalized:
            return
        with self._lock:
            new_symbols = [symbol for symbol in normalized if symbol not in self._subscribed_symbols]
            self._subscribed_symbols.update(new_symbols)
            socket = self._socket
        if new_symbols and socket is not None:
            try:
                socket.subscribe(new_symbols)
            except Exception as exc:
                logger.warning("Tick stream subscribe failed for %s: %s", new_symbols, exc)

    def unsubscribe(self, symbols: list[str]) -> None:
        normalized = [str(symbol).upper() for symbol in symbols if str(symbol).strip()]
        if not normalized:
            return
        with self._lock:
            remove_symbols = [symbol for symbol in normalized if symbol in self._subscribed_symbols]
            for symbol in remove_symbols:
                self._subscribed_symbols.discard(symbol)
            socket = self._socket
        if remove_symbols and socket is not None:
            try:
                socket.unsubscribe(remove_symbols)
            except Exception as exc:
                logger.warning("Tick stream unsubscribe failed for %s: %s", remove_symbols, exc)

    def stop(self) -> None:
        with self._lock:
            self._running = False
            self._intentional_stop = True
            self._reconnect_scheduled = False
            socket = self._socket
            self._socket = None
        if socket is not None:
            try:
                socket.close_connection()
            except Exception as exc:
                logger.warning("Tick stream stop failed: %s", exc)

    def _socket_class(self):
        return getattr(fyersModel, "FyersDataSocket", None) or _FyersDataSocket

    def _connect_socket(self) -> None:
        try:
            socket_cls = self._socket_class()
            access_token = str(self._access_token_getter() or "")
            if socket_cls is None or not access_token:
                raise RuntimeError("Fyers websocket unavailable or token missing")

            socket = socket_cls(
                access_token=access_token,
                write_to_file=False,
                log_path="",
                litemode=False,
                reconnect=False,
                on_message=self._handle_message,
                on_error=self._handle_error,
                on_connect=self._handle_connect,
                on_close=self._handle_close,
            )
            with self._lock:
                if not self._running or self._intentional_stop:
                    return
                self._socket = socket
            socket.connect()
        except Exception as exc:
            logger.warning("Tick stream connect failed: %s", exc)
            self._schedule_reconnect()

    def _handle_connect(self) -> None:
        with self._lock:
            self._reconnect_attempts = 0
            self._reconnect_scheduled = False
            socket = self._socket
            symbols = sorted(self._subscribed_symbols)
        if socket is not None and symbols:
            try:
                socket.subscribe(symbols)
            except Exception as exc:
                logger.warning("Tick stream resubscribe failed: %s", exc)

    def _handle_close(self, message) -> None:
        logger.warning("Tick stream closed: %s", message)
        with self._lock:
            self._socket = None
        self._schedule_reconnect()

    def _handle_error(self, error) -> None:
        logger.warning("Tick stream error: %s", error)
        with self._lock:
            self._socket = None
        self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        with self._lock:
            if not self._running or self._intentional_stop:
                return
            if self._reconnect_scheduled:
                return
            self._reconnect_attempts += 1
            self._reconnect_scheduled = True
            # Exponential backoff: 5s, 10s, 20s, 40s … capped at 120s
            delay = min(5 * (2 ** (self._reconnect_attempts - 1)), 120)
        threading.Thread(target=self._reconnect_after_delay, args=(delay,), daemon=True).start()

    def _reconnect_after_delay(self, delay: float = 5) -> None:
        time.sleep(delay)
        with self._lock:
            self._reconnect_scheduled = False
            if not self._running or self._intentional_stop:
                return
        self._connect_socket()

    def _handle_message(self, message: dict) -> None:
        on_tick = self._on_tick
        if on_tick is None:
            return
        for symbol, ltp in self._extract_ticks(message):
            try:
                on_tick(symbol, ltp)
            except Exception as exc:
                logger.warning("Tick callback failed for %s: %s", symbol, exc)

    def _extract_ticks(self, message: dict) -> list[tuple[str, float]]:
        ticks: list[tuple[str, float]] = []
        if not isinstance(message, dict):
            return ticks

        symbol = message.get("symbol") or message.get("n")
        ltp = message.get("ltp")
        if ltp is None:
            ltp = message.get("lp")
        if symbol and ltp is not None:
            try:
                val = float(ltp)
                if not math.isnan(val):
                    ticks.append((str(symbol).upper(), val))
            except (TypeError, ValueError):
                pass

        raw_ticks = message.get("d")
        if isinstance(raw_ticks, list):
            for item in raw_ticks:
                if not isinstance(item, dict):
                    continue
                raw_symbol = item.get("symbol") or item.get("n")
                raw_ltp = item.get("ltp")
                if raw_ltp is None:
                    raw_ltp = item.get("lp")
                if raw_ltp is None and isinstance(item.get("v"), dict):
                    raw_ltp = item["v"].get("lp")
                if raw_symbol and raw_ltp is not None:
                    try:
                        val = float(raw_ltp)
                        if not math.isnan(val):
                            ticks.append((str(raw_symbol).upper(), val))
                    except (TypeError, ValueError):
                        continue

        deduped: dict[str, float] = {}
        for tick_symbol, tick_ltp in ticks:
            deduped[tick_symbol] = tick_ltp
        return list(deduped.items())


fyers_tick_stream = FyersTickStream(
    access_token_getter=lambda: fyers_client.get_ws_access_token()
)
