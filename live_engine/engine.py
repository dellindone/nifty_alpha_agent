from __future__ import annotations

import logging
import os
import signal
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from candle_poll import CandlePoll
from display import Display
from eod_handler import EODHandler
from lib.journal import TradeJournal
from lib.reporter import Reporter
from lib.signal_handler import SignalHandler
from health import AgentHealth
from health_monitor import HealthMonitor
from shadow_mode import ShadowModeExecutor
from signal_router import SignalRouter
from tick_handler import TickHandler
from config.instruments import FYERS_SYMBOL
from config.settings import IST, Paths
from ingestion.fyers_client import fyers_client, fyers_tick_stream
from model.predict import NiftyPredictor
from risk.capital_tracker import CapitalTracker
from utils.market_calendar import is_trading_day

logger = logging.getLogger(__name__)
class Engine:
    def __init__(self, instrument: str, artifacts_dir: str | Path, tick_stream=None, live: bool = False) -> None:
        self.instrument = instrument.upper()
        path = Path(artifacts_dir)
        self.artifacts_dir = path if path.is_absolute() else (Paths.ROOT / path).resolve()
        self.data_dir = Paths.DATA_DIRS[self.instrument.lower()]
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.predictor = NiftyPredictor()
        self.predictor.load(self.artifacts_dir, self.instrument)
        self.signal_handler = SignalHandler()
        self.journal = TradeJournal(self.data_dir)
        self.capital_tracker = CapitalTracker(data_dir=self.data_dir)
        self.reporter = Reporter(self.journal, self.capital_tracker, os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", ""))
        self.health = AgentHealth()
        self.health_monitor = HealthMonitor(self.health, self.reporter)
        if live:
            from live_mode import LiveModeExecutor
            self.shadow_mode = LiveModeExecutor(journal=self.journal, capital_tracker=self.capital_tracker, health=self.health)
        else:
            self.shadow_mode = ShadowModeExecutor(journal=self.journal, capital_tracker=self.capital_tracker)
        self._running, self._last_daily_pnl, self._last_daily_count = True, 0.0, 0
        self._eod_closed_on = self._summary_sent_on = self._daily_target_alerted_on = self._started_at_ist = self._last_hourly_heartbeat_key = None
        self._tick_stream = tick_stream if tick_stream is not None else fyers_tick_stream
        self._subscribed_symbols: set[str] = set()
        fyers_client.get_session()
        self._tick_lock = threading.Lock()
        self._display_line_count = self._poll_count = 0
        self._last_index_price = self._last_vix = self._last_atr = 0.0
        self._last_decision = "STARTING"
        self._last_pred_data: dict[str, object] = {}
        self._last_current_premiums: dict[str, float] = {}
        self._tick_handler, self._display, self._signal_router = TickHandler(self), Display(self), SignalRouter(self)
        self._eod_handler, self._candle_poll = EODHandler(self), CandlePoll(self)
        for helper, names in (
            (self._tick_handler, ("_on_tick", "_ensure_subscribed", "_unsubscribe_if_unused", "_get_open_trade_symbols")),
            (self._display, ("_print_live_display", "_log_poll")),
            (self._signal_router, ("_handle_trade_signal", "_build_no_signal_decision", "_resolve_option_symbol", "_resolve_option_symbol_from_signal")),
            (self._eod_handler, ("_handle_schedule_tasks", "_maybe_send_hourly_heartbeat", "_current_premiums_for_open_trades")),
            (self._candle_poll, ("_run_candle_poll", "_fetch_live_frames", "_daily_realized_pnl", "_daily_trade_count_today")),
        ):
            for name in names:
                setattr(self, name, getattr(helper, name))

    def _setup(self) -> None:
        """Initialise runtime state and subscribe to symbols. Called before _run_loop()."""
        self._started_at_ist = datetime.now(IST)
        open_trades = self.shadow_mode.open_trades()
        self.reporter.send_startup_summary(
            self.instrument, self._started_at_ist,
            [{"instrument": t.signal.instrument, "option_type": t.signal.option_type,
              "strike": t.signal.strike, "expiry_date": t.signal.expiry_date,
              "entry_premium": t.signal.entry_premium, "current_sl": t.current_sl,
              "target_price": t.signal.target_price, "confidence": t.signal.confidence,
              "lots": getattr(t, "lots", 1), "trail_active": t.trail_active}
             for t in open_trades],
        )
        if open_trades:
            logger.info("Restored %d open trade(s) for %s", len(open_trades), self.instrument)
        with self._tick_lock:
            self._ensure_subscribed([FYERS_SYMBOL[self.instrument]])
            self._ensure_subscribed(self._get_open_trade_symbols())

    def _run_loop(self) -> None:
        """Main poll loop. Runs until self._running is False."""
        def _market_open(now_ist: datetime) -> bool:
            if now_ist.weekday() >= 5 or not is_trading_day(now_ist.date()):
                return False
            market_open  = now_ist.replace(hour=9,  minute=15, second=0, microsecond=0)
            market_close = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
            return market_open <= now_ist <= market_close

        def _is_within_run_window(now_ist: datetime) -> bool:
            start = now_ist.replace(hour=9,  minute=10, second=0, microsecond=0)
            end   = now_ist.replace(hour=15, minute=35, second=59, microsecond=0)
            return start <= now_ist <= end and now_ist.weekday() < 5

        while self._running:
            now_ist = datetime.now(IST)
            self._handle_schedule_tasks(now_ist)
            self._maybe_send_hourly_heartbeat(now_ist)
            if _is_within_run_window(now_ist):
                self._run_candle_poll(now_ist) if _market_open(now_ist) else self._log_poll(now_ist, "MARKET_CLOSED")
            self.health_monitor.check_and_alert()
            self._sleep_until_next_five_minute_mark()

    def run(self) -> None:
        """Single-instrument entry point — unchanged public API."""
        self._install_signal_handlers()
        logger.info("Engine started for %s", self.instrument)
        self._setup()
        self._tick_stream.start(on_tick=self._on_tick)
        try:
            self._run_loop()
        finally:
            self._tick_stream.stop()
            logger.info("Engine stopped gracefully for %s", self.instrument)

    def _install_signal_handlers(self) -> None:
        def _handle_shutdown_signal(signum, _frame) -> None:
            logger.info("shutdown_signal_received signal=%s", signum)
            self._running = False

        signal.signal(signal.SIGINT, _handle_shutdown_signal)
        signal.signal(signal.SIGTERM, _handle_shutdown_signal)

    def _sleep_until_next_five_minute_mark(self) -> None:
        now_ist = datetime.now(IST)
        minute = now_ist.minute
        next_minute = ((minute // 5) + 1) * 5
        target = now_ist.replace(second=0, microsecond=0)
        target = (target + timedelta(hours=1)).replace(minute=0) if next_minute >= 60 else target.replace(minute=next_minute)
        time.sleep(max(0.1, (target - now_ist).total_seconds()))
