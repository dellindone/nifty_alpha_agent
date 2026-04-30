import base64
import logging
import os
import time
from urllib.parse import parse_qs, urlparse

import certifi
import pyotp
import requests
from dotenv import load_dotenv
from fyers_apiv3 import fyersModel

from config.settings import Equity
from ingestion.brokers.base import AbstractBroker

load_dotenv()
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
logger = logging.getLogger(__name__)


class FyersBroker(AbstractBroker):
    def __init__(self, credentials="primary") -> None:
        self.credentials, self._session, self._login_time = credentials, None, None

    def _env(self, key: str) -> str:
        return os.getenv(key if self.credentials == "primary" else f"{key}_2", "")

    def _is_token_expired(self) -> bool:
        return self._login_time is None or (time.time() - self._login_time) > Equity.TOKEN_MAX_AGE_SECONDS

    def _encoded(self, value: str) -> str:
        return base64.b64encode(value.encode("ascii")).decode("ascii")

    def _login(self):
        try:
            fy_id, client_id, secret_key = self._env("FYERS_ID"), self._env("FYERS_CLIENT_ID"), self._env("FYERS_SECRET_KEY")
            redirect_uri, totp_secret, pin = self._env("FYERS_REDIRECT_URI"), self._env("FYERS_TOTP_SECRET"), self._env("FYERS_PIN")
            res = requests.post("https://api-t2.fyers.in/vagator/v2/send_login_otp_v2", json={"fy_id": self._encoded(fy_id), "app_id": "2"}).json()
            if res.get("s") != "ok":
                return None
            if time.localtime().tm_sec % 30 > 27:
                time.sleep(5)
            res = requests.post("https://api-t2.fyers.in/vagator/v2/verify_otp", json={"request_key": res["request_key"], "otp": pyotp.TOTP(totp_secret).now()}).json()
            if res.get("s") != "ok":
                return None
            ses = requests.Session()
            res = ses.post("https://api-t2.fyers.in/vagator/v2/verify_pin_v2", json={"request_key": res["request_key"], "identity_type": "pin", "identifier": self._encoded(pin)}).json()
            if res.get("s") != "ok":
                return None
            ses.headers.update({"authorization": f"Bearer {res['data']['access_token']}"})
            res = ses.post("https://api-t1.fyers.in/api/v3/token", json={"fyers_id": fy_id, "app_id": client_id[:-4], "redirect_uri": redirect_uri, "appType": "100", "response_type": "code", "create_cookie": True}).json()
            if res.get("s") != "ok":
                return None
            auth_code = parse_qs(urlparse(res["Url"]).query).get("auth_code", [None])[0]
            sess = fyersModel.SessionModel(client_id=client_id, secret_key=secret_key, redirect_uri=redirect_uri, response_type="code", grant_type="authorization_code")
            sess.set_token(auth_code)
            token_resp = sess.generate_token()
            return None if not token_resp or not token_resp.get("access_token") else fyersModel.FyersModel(client_id=client_id, token=token_resp["access_token"], is_async=False, log_path="")
        except Exception as e:
            logger.error("Fyers login exception: %s", e)
            return None

    def _get_session(self):
        if self._session is None or self._is_token_expired():
            session = self._login()
            if session is not None:
                self._session = session
                self._login_time = time.time()
        return self._session

    def get_historical(self, symbol: str, resolution: str, date_from: str, date_to: str) -> list:
        session = self._get_session()
        if not session:
            return []
        try:
            data = session.history({"symbol": symbol, "resolution": resolution, "date_format": "1", "range_from": date_from, "range_to": date_to, "cont_flag": "1"})
            return data.get("candles", []) if data.get("s") == "ok" else []
        except Exception as e:
            logger.error("Fyers historical error: %s", e)
            return []

    def get_quote(self, symbols: list[str]) -> list[dict]:
        session = self._get_session()
        if not session:
            return []
        try:
            return session.quotes({"symbols": ",".join(symbols)}).get("d", [])
        except Exception as e:
            logger.error("Fyers quote error: %s", e)
            return []
