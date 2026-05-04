"""Market replay — feeds historical feature rows through the live signal pipeline.

Usage (from repo root):
    python main.py --replay --date 2026-05-04
    python main.py --replay --date 2026-05-04 --dataset /path/to/features.parquet
    python main.py --replay --date 2026-05-04 --speed 5   # 5s pause between bars
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from config.settings import IST, Paths, get_instrument_config
from lib.signal_handler import TradeSignal
from lib.reporter import Reporter
from lib.journal import TradeJournal
from model.predict import NiftyPredictor, ModelPrediction
from risk.capital_tracker import CapitalTracker
from risk.position_sizer import stop_loss_from_bin
from config.instruments import LOT_SIZES
from utils.market_calendar import next_expiry, market_calendar
from ingestion.synthetic_premium import synthetic_premium

logger = logging.getLogger(__name__)

_DEFAULT_DATASET = str(
    Path(__file__).resolve().parents[3]
    / "trading_research/data/nifty/NIFTY_features_v5_oos_2026.parquet"
)
_STRIKE_STEP = {"NIFTY": 50, "BANKNIFTY": 100, "SENSEX": 100}


@dataclass
class _OpenTrade:
    trade_id: str
    direction: int       # 1=CE 0=PE
    entry_close: float
    sl_dist: float
    target_dist: float
    entry_bar: int
    lots: int
    bars_held: int = 0
    trail_active: bool = False
    trail_peak: float = 0.0   # highest favorable price seen once trail is on
    trail_stop: float = 0.0   # current trail SL level (in move pts from entry)


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
        self.predictor = NiftyPredictor()
        self.predictor.load(Path(artifacts_dir), self.instrument)
        data_dir = Paths.DATA_DIRS[self.instrument.lower()]
        data_dir.mkdir(parents=True, exist_ok=True)
        cap = CapitalTracker(data_dir=data_dir)
        self.reporter = Reporter(
            TradeJournal(data_dir), cap,
            os.getenv("TELEGRAM_BOT_TOKEN", ""),
            os.getenv("TELEGRAM_CHAT_ID", ""),
        )
        self.reporter.mode = "REPLAY"
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

    def _make_signal(
        self,
        prediction: ModelPrediction,
        row: pd.Series,
        now_ist: datetime,
        daily_pnl: float,
        daily_count: int,
    ) -> tuple[TradeSignal | None, str]:
        """Run all filter checks and build TradeSignal from parquet data (no live option chain)."""
        cfg = get_instrument_config(self.instrument)

        if not prediction.should_trade or prediction.trade_class == "NO_TRADE":
            return None, "MODEL_NO_TRADE"
        if len(self._open_trades) > 0:
            return None, f"TRADE_ALREADY_OPEN ({len(self._open_trades)} open)"

        sb = int(row.get("session_bar", 999))
        if sb < cfg.min_session_bar:
            return None, f"TOO_EARLY bar={sb} min={cfg.min_session_bar}"
        if prediction.confidence < cfg.min_confidence:
            return None, f"LOW_CONF {prediction.confidence:.0%} < {cfg.min_confidence:.0%}"
        if daily_pnl <= -abs(cfg.daily_loss_limit):
            return None, f"DAILY_LOSS_LIMIT pnl=₹{daily_pnl:.0f}"
        if daily_count >= cfg.max_trades_per_day:
            return None, f"MAX_TRADES({daily_count})"

        atr = float(row.get("atr_14", 0.0))
        vix = float(row.get("vix", 0.0))
        if atr <= 0:
            return None, "ZERO_ATR"

        sl = float(stop_loss_from_bin(prediction.sl_bin, atr, vix, cfg=cfg))
        tp = float(prediction.phase1_target)
        if tp <= 0 or sl <= 0:
            return None, f"ZERO_SL_OR_TARGET sl={sl:.2f} tp={tp:.2f}"
        rr = tp / sl
        if rr < cfg.min_rr:
            return None, f"LOW_RR {rr:.2f} < {cfg.min_rr} (sl={sl:.2f} tp={tp:.2f})"

        option_type = "CE" if prediction.direction == 1 else "PE"
        close = float(row.get("close", 0.0))
        step = _STRIKE_STEP.get(self.instrument, 50)
        atm = int(round(close / step) * step)
        # Mirror live strike_selector NORMAL mode: 2 ITM
        strike = (atm - 2 * step) if option_type == "CE" else (atm + 2 * step)

        # Price the actual 2 ITM strike via Black-Scholes (not ATM parquet column)
        dte = max(1, market_calendar.days_to_next_expiry(self.instrument, now_ist.date()))
        entry_premium = synthetic_premium.compute(
            spot=close,
            strike=strike,
            days_to_expiry=dte,
            volatility_pct=vix if vix > 0 else 15.0,
            risk_free_rate=6.5,
            option_type=option_type,
        ) or float(row.get("ce_premium" if option_type == "CE" else "pe_premium", 0.0))
        lot_size = LOT_SIZES.get(self.instrument, 50)
        expiry = next_expiry(self.instrument, now_ist.date())

        signal = TradeSignal(
            instrument=self.instrument,
            direction=prediction.direction,
            option_type=option_type,
            strike=strike,
            expiry_date=expiry,
            entry_premium=entry_premium,
            sl_price=sl,
            target_price=tp,
            trail_bin=str(prediction.trail_bin),
            trail_tf=str(prediction.trail_tf),
            confidence=float(prediction.confidence),
            direction_prob=float(prediction.direction_prob),
            vix=vix,
            atr=atr,
            lot_size=lot_size,
            lots=1,
        )
        return signal, ""

    def _check_open_trades(self, close: float, now_ist: datetime) -> None:
        cfg = get_instrument_config(self.instrument)
        thresh = cfg.trail_activation_rr  # multiplier on sl_dist for trail activation
        width_mult = cfg.trail_width_mult  # trail stop = peak - width_mult * sl_dist
        lot_size = LOT_SIZES.get(self.instrument, 50)
        still_open = []

        for t in self._open_trades:
            t.bars_held += 1
            move = (close - t.entry_close) if t.direction == 1 else (t.entry_close - close)
            reason = None

            # Trail activation: when move reaches trail_activation_rr × sl_dist
            if not t.trail_active and move >= thresh * t.sl_dist:
                t.trail_active = True
                t.trail_peak = move
                t.trail_stop = t.trail_peak - width_mult * t.sl_dist

            # Update trail peak and stop
            if t.trail_active:
                if move > t.trail_peak:
                    t.trail_peak = move
                    t.trail_stop = t.trail_peak - width_mult * t.sl_dist
                if move <= t.trail_stop:
                    reason = "TRAIL_STOP"

            # Hard SL (only before trail activates)
            if not t.trail_active and move <= -t.sl_dist:
                reason = "SL_HIT"

            # Hard target exit
            if move >= t.target_dist:
                reason = "TARGET_HIT"

            if t.bars_held >= 78:
                reason = "EOD_EXIT"

            if reason:
                pnl = (move - 0.05) * lot_size * t.lots
                icon = "✅" if pnl >= 0 else "🔴"
                direction_label = "CE" if t.direction == 1 else "PE"
                trail_info = f"  trail_peak={t.trail_peak:+.1f}" if t.trail_active else ""
                logger.info("REPLAY_EXIT trade_id=%s reason=%s move=%.1f pnl=₹%.0f bars=%d", t.trade_id, reason, move, pnl, t.bars_held)
                print(f"  [{now_ist.strftime('%H:%M')}] EXIT {reason}  move={move:+.1f}{trail_info}  pnl=₹{pnl:,.0f}  bars={t.bars_held}")
                self.reporter._send(
                    f"[REPLAY {self.replay_date} {now_ist.strftime('%H:%M')} IST]\n"
                    f"{icon} EXIT {reason} — {self.instrument} {direction_label}\n"
                    f"Move: {move:+.1f} pts | Trail peak: {t.trail_peak:+.1f} pts | Bars: {t.bars_held}\n"
                    f"PnL: ₹{pnl:,.0f}"
                )
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

        missing = [f for f in self.predictor.selected_features if f not in bars.columns]
        if missing:
            print(f"WARNING: {len(missing)} features missing: {missing[:3]}...")

        daily_pnl, daily_count = 0.0, 0

        for bar_idx, (ts, row_series) in enumerate(bars.iterrows()):
            now_ist = ts.tz_convert(IST)
            close = float(row_series.get("close", 0.0))
            self._check_open_trades(close, now_ist)

            try:
                prediction = self.predictor.predict(pd.DataFrame([row_series]))
            except Exception as exc:
                logger.warning("predict failed bar=%d: %s", bar_idx, exc)
                continue

            signal, block_reason = self._make_signal(prediction, row_series, now_ist, daily_pnl, daily_count)
            conf = f"{prediction.confidence:.0%}"
            tc = str(prediction.trade_class or "")
            sb = int(row_series.get("session_bar", -1))

            if signal is not None:
                rr = signal.target_price / signal.sl_price
                self._trade_seq += 1
                self._open_trades.append(_OpenTrade(
                    trade_id=f"REPLAY_{self._trade_seq:03d}",
                    direction=signal.direction,
                    entry_close=close,
                    sl_dist=signal.sl_price,
                    target_dist=signal.target_price,
                    entry_bar=bar_idx,
                    lots=signal.lots,
                ))
                daily_count += 1
                msg = (f"  [{now_ist.strftime('%H:%M')}] BAR={sb:>2}  SIGNAL {signal.option_type}"
                       f"  strike={signal.strike}  entry=₹{signal.entry_premium:.2f}"
                       f"  conf={conf}  rr={rr:.2f}  sl={signal.sl_price:.1f}  tp={signal.target_price:.1f}  *** ENTERED ***")
                logger.info("REPLAY_ENTRY %s", msg)
                self.reporter._send(
                    f"[REPLAY {self.replay_date} {now_ist.strftime('%H:%M')} IST]\n"
                    f"🟡 {signal.option_type} {signal.strike} | Expiry: {signal.expiry_date.strftime('%d-%b-%y')}\n"
                    f"Entry: ₹{signal.entry_premium:.2f} | SL: ₹{signal.sl_price:.2f} | Target: ₹{signal.target_price:.2f}\n"
                    f"RR: {rr:.2f} | Confidence: {conf} | VIX: {signal.vix:.1f}"
                )
            else:
                msg = f"  [{now_ist.strftime('%H:%M')}] BAR={sb:>2}  {tc:<15} conf={conf}  {block_reason}"
                logger.info("REPLAY_POLL %s", msg)

            print(msg)
            if self.speed > 0:
                time.sleep(self.speed)

        print(f"\n{'='*62}")
        print(f"  Trades entered: {daily_count}  |  Open at EOD: {len(self._open_trades)}")
        print(f"{'='*62}\n")
