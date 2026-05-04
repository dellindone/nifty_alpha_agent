"""Market replay — feeds historical feature rows through the live signal pipeline.

Usage (from repo root):
    python main.py --replay --date 2026-05-04
    python main.py --replay --date 2026-05-04 --dataset /path/to/features.parquet
    python main.py --replay --date 2026-05-04 --speed 0   # instant (default)
    python main.py --replay --date 2026-05-04 --speed 5   # 5s pause between bars
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from config.settings import IST, Paths
from lib.signal_handler import SignalHandler
from lib.reporter import Reporter
from lib.journal import TradeJournal
from model.predict import NiftyPredictor
from risk.capital_tracker import CapitalTracker
from risk.position_sizer import stop_loss_from_bin
from config.instruments import LOT_SIZES

logger = logging.getLogger(__name__)

_DEFAULT_DATASET = str(
    Path(__file__).resolve().parents[3]
    / "trading_research/data/nifty/NIFTY_features_v5_oos_2026.parquet"
)


@dataclass
class _OpenTrade:
    trade_id: str
    direction: int          # 1=CE 0=PE
    entry_close: float
    sl_dist: float
    target_dist: float
    entry_bar: int
    lots: int
    entry_premium: float = 0.0
    bars_held: int = 0


class ReplayRunner:
    def __init__(
        self,
        instrument: str,
        artifacts_dir: str | Path,
        replay_date: str,
        dataset_path: str | None = None,
        speed: float = 0.0,
    ) -> None:
        self.instrument = instrument.upper()
        self.replay_date = replay_date
        self.speed = speed
        self.dataset_path = dataset_path or _DEFAULT_DATASET
        art = Path(artifacts_dir)
        self.predictor = NiftyPredictor()
        self.predictor.load(art, self.instrument)
        self.signal_handler = SignalHandler()
        data_dir = Paths.DATA_DIRS[self.instrument.lower()]
        data_dir.mkdir(parents=True, exist_ok=True)
        journal = TradeJournal(data_dir)
        cap = CapitalTracker(data_dir=data_dir)
        self.reporter = Reporter(
            journal, cap,
            os.getenv("TELEGRAM_BOT_TOKEN", ""),
            os.getenv("TELEGRAM_CHAT_ID", ""),
        )
        self._open_trades: list[_OpenTrade] = []
        self._trade_seq = 0

    def _load_bars(self) -> pd.DataFrame:
        df = pd.read_parquet(self.dataset_path).sort_index()
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index, utc=True)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        ist = df.index.tz_convert("Asia/Kolkata")
        return df[ist.date == pd.Timestamp(self.replay_date).date()]

    def _check_open_trades(self, close: float, now_ist: datetime, bar_idx: int) -> None:
        still_open = []
        for t in self._open_trades:
            t.bars_held += 1
            move = (close - t.entry_close) if t.direction == 1 else (t.entry_close - close)
            reason = None
            if move <= -t.sl_dist:
                reason = "SL_HIT"
            elif move >= t.target_dist:
                reason = "TARGET_HIT"
            elif t.bars_held >= 78:
                reason = "EOD_EXIT"
            if reason:
                pnl = (move - 0.05) * LOT_SIZES.get(self.instrument, 50) * t.lots
                logger.info(
                    "REPLAY_EXIT trade_id=%s reason=%s move=%.1f pnl=₹%.0f bars=%d",
                    t.trade_id, reason, move, pnl, t.bars_held,
                )
                print(f"  [{now_ist.strftime('%H:%M')}] EXIT {reason}  move={move:+.1f}  pnl=₹{pnl:,.0f}  bars={t.bars_held}")
            else:
                still_open.append(t)
        self._open_trades = still_open

    def run(self) -> None:
        bars = self._load_bars()
        if bars.empty:
            print(f"No data for {self.replay_date} in {self.dataset_path}")
            return

        print(f"\n{'='*62}")
        print(f"REPLAY  {self.replay_date}  |  {len(bars)} bars  |  model={self.instrument}")
        print(f"{'='*62}")

        daily_pnl, daily_count = 0.0, 0
        missing = [f for f in self.predictor.selected_features if f not in bars.columns]
        if missing:
            print(f"WARNING: {len(missing)} features missing from dataset: {missing[:3]}...")

        for bar_idx, (ts, row_series) in enumerate(bars.iterrows()):
            now_ist = ts.tz_convert(IST)
            feature_row = pd.DataFrame([row_series])
            close = float(row_series.get("close", 0.0))

            self._check_open_trades(close, now_ist, bar_idx)

            try:
                prediction = self.predictor.predict(feature_row)
            except Exception as exc:
                logger.warning("predict failed bar=%d: %s", bar_idx, exc)
                continue

            signal = self.signal_handler.process(
                prediction=prediction,
                feature_row=feature_row,
                instrument=self.instrument,
                daily_pnl=daily_pnl,
                daily_trade_count=daily_count,
            )

            conf = f"{prediction.confidence:.0%}"
            tc = prediction.trade_class
            sb = int(row_series.get("session_bar", -1))
            atr = float(row_series.get("atr_14", 0.0))

            if signal is not None and not signal.blocked:
                sl = signal.sl_price
                tp = signal.target_price
                rr = tp / sl if sl > 0 else 0
                self._trade_seq += 1
                tid = f"REPLAY_{self._trade_seq:03d}"
                self._open_trades.append(_OpenTrade(
                    trade_id=tid, direction=signal.direction,
                    entry_close=close, sl_dist=sl, target_dist=tp,
                    entry_bar=bar_idx, lots=signal.lots,
                ))
                daily_count += 1
                msg = (f"  [{now_ist.strftime('%H:%M')}] BAR={sb:>2}  SIGNAL {signal.option_type}"
                       f"  conf={conf}  rr={rr:.2f}  sl={sl:.1f}  tp={tp:.1f}  *** ENTERED ***")
                logger.info("REPLAY_ENTRY %s", msg)
                self.reporter.send_signal_alert(signal)
            elif signal is not None and signal.blocked:
                msg = (f"  [{now_ist.strftime('%H:%M')}] BAR={sb:>2}  {tc:<15} conf={conf}"
                       f"  BLOCKED({signal.block_reason})")
                logger.info("REPLAY_BLOCKED %s", msg)
            else:
                reason = self.signal_handler.last_block_reason or "NO_SIGNAL"
                msg = f"  [{now_ist.strftime('%H:%M')}] BAR={sb:>2}  {tc:<15} conf={conf}  {reason}"
                logger.info("REPLAY_POLL %s", msg)

            print(msg)
            if self.speed > 0:
                time.sleep(self.speed)

        print(f"\n{'='*62}")
        print(f"  Total signals entered: {daily_count}  |  Open at EOD: {len(self._open_trades)}")
        print(f"{'='*62}\n")
