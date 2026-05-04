"""Base reporter — shared Telegram delivery logic for all agents."""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime

import httpx

from config.settings import IST, Logging

logger = logging.getLogger(__name__)


class BaseReporter(ABC):
    """
    Handles all Telegram communication. Subclasses implement
    instrument-specific message formatting; this class owns delivery.
    """

    def __init__(self, telegram_token: str = "", telegram_chat_id: str = "", mode: str = "") -> None:
        self.telegram_token   = str(telegram_token   or Logging.TELEGRAM_BOT_TOKEN)
        self.telegram_chat_id = str(telegram_chat_id or Logging.TELEGRAM_CHAT_ID)
        self.mode = str(mode or os.getenv("AGENT_MODE", "SHADOW")).upper()

    # ── Abstract interface ────────────────────────────────────────────────────

    @abstractmethod
    def send_signal_alert(self, signal) -> None: ...

    @abstractmethod
    def send_exit_alert(self, record) -> None: ...

    @abstractmethod
    def send_daily_summary(self, *args, **kwargs) -> None: ...

    # ── Shared implementations ────────────────────────────────────────────────

    def send_engine_start_alert(self, instrument: str, started_at: datetime) -> None:
        local = started_at.astimezone(IST) if started_at.tzinfo else IST.localize(started_at)
        mode_label = "Paper/Shadow" if self.mode == "SHADOW" else "Live Trading"
        self._send(
            f"🟢 {instrument} AGENT STARTED\n"
            f"Started: {local.strftime('%d-%b-%Y %H:%M:%S IST')}\n"
            f"Mode: {mode_label}\n"
            "Status: Heartbeat enabled (hourly)"
        )

    def send_hourly_live_summary(
        self,
        *,
        instrument: str,
        open_trades: int,
        trades_today: int,
        capital: float,
        uptime_minutes: int,
        index_price: float = 0.0,
    ) -> None:
        price_str = f"${index_price:,.0f}" if "BTC" in instrument.upper() else f"₹{index_price:,.0f}"
        self._send(
            f"💓 {instrument} HEARTBEAT\n"
            f"{instrument}: {price_str} | Open: {open_trades} | Trades today: {trades_today}\n"
            f"Capital: ₹{capital:,.0f} | Uptime: {uptime_minutes}min\n"
            "Proof: Agent loop active and polling market data."
        )

    def _send(self, message: str, retries: int = 3) -> None:
        if not self.telegram_token or not self.telegram_chat_id:
            logger.warning("Telegram credentials not configured; skipping send.")
            return
        tagged_message = f"[{self.mode}] {message}"
        url     = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {"chat_id": self.telegram_chat_id, "text": tagged_message}
        last_exc: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                with httpx.Client(timeout=10.0) as client:
                    client.post(url, json=payload).raise_for_status()
                return
            except Exception as exc:
                last_exc = exc
                logger.warning("Telegram send failed (attempt %d/%d): %s", attempt, retries, exc)
                if attempt < retries:
                    time.sleep(1.0)
        logger.warning("Telegram send permanently failed: %s", last_exc)
