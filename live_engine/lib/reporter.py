"""Telegram reporter for shadow trading signals, exits, and daily summaries."""

from __future__ import annotations

import logging
import os
from datetime import datetime

import pandas as pd

from lib.journal import Journal, TradeRecord
from lib.signal_handler import TradeSignal
from base.reporter import BaseReporter
from risk.capital_tracker import CapitalTracker
from config.settings import IST

logger = logging.getLogger(__name__)


class Reporter(BaseReporter):
    """Nifty/Sensex/BankNifty message formatting. Delivery handled by BaseReporter."""

    def __init__(
        self,
        journal: Journal,
        capital_tracker: CapitalTracker,
        telegram_token: str = "",
        telegram_chat_id: str = "",
    ) -> None:
        super().__init__(telegram_token, telegram_chat_id)
        self.journal = journal
        self.capital_tracker = capital_tracker
        self.telegram_token = str(telegram_token or os.getenv("TELEGRAM_BOT_TOKEN", "") or "")
        self.telegram_chat_id = str(telegram_chat_id or os.getenv("TELEGRAM_CHAT_ID", "") or "")

    def _contract(self, instrument: str, expiry_date, strike: int, option_type: str) -> str:
        expiry = pd.to_datetime(expiry_date, errors="coerce")
        exp = expiry.strftime("%d%b").upper() if not pd.isna(expiry) else "?"
        return f"{str(instrument).upper()}{exp}{int(strike)}{str(option_type).upper()}"

    def send_signal_alert(self, signal: TradeSignal, blocked: bool = False) -> None:
        contract = self._contract(signal.instrument, signal.expiry_date, signal.strike, "CE" if signal.direction == 1 else "PE")
        confidence_pct = int(round(float(signal.confidence) * 100))
        if blocked:
            message = (
                f"👁 SIGNAL (NOT PUNCHED) — {signal.instrument}\n"
                f"Contract: {contract}\n"
                f"Entry: ₹{signal.entry_premium:.2f} | SL: ₹{signal.sl_price:.2f} | Target: ₹{signal.target_price:.2f}\n"
                f"Confidence: {confidence_pct}% | VIX: {signal.vix:.1f}\n"
                f"Reason: {signal.block_reason}"
            )
        else:
            message = (
                f"🟢 SHADOW SIGNAL — {signal.instrument}\n"
                f"Contract: {contract}\n"
                f"Entry: ₹{signal.entry_premium:.2f} | SL: ₹{signal.sl_price:.2f} | Target: ₹{signal.target_price:.2f}\n"
                f"Confidence: {confidence_pct}% | VIX: {signal.vix:.1f}"
            )
        self._send(message)

    def send_health_alert(self, message: str) -> None:
        self._send(message)

    def send_exit_alert(self, record: TradeRecord) -> None:
        contract = self._contract(record.instrument, record.expiry_date, record.strike, "CE" if int(record.direction) == 1 else "PE")
        pnl_net  = float(record.pnl_net or 0.0)
        charges  = float(record.charges or 0.0)
        lots     = int(record.lots or 1)
        sign     = "+" if pnl_net >= 0 else "-"
        icon     = "✅" if pnl_net > 0 else "🔴"
        message  = (
            f"{icon} EXIT — {contract}  {lots} lots\n"
            f"Reason : {record.exit_reason or 'UNKNOWN'}\n"
            f"Entry  : ₹{float(record.entry_premium):.2f}  →  Exit: ₹{float(record.exit_premium or 0):.2f}\n"
            f"Net P&L: {sign}₹{abs(pnl_net):.2f}  |  Charges: ₹{charges:.2f}"
        )
        self._send(message)

    def send_daily_summary(self) -> None:
        df = self.journal.load_all()
        now_ist = datetime.now(IST)
        if df.empty:
            message = (
                f"📊 DAILY SHADOW SUMMARY — {now_ist.strftime('%d %b %Y')}\n"
                "Trades: 0 | Wins: 0 | Losses: 0 | Win Rate: 0%\n"
                "Gross P&L: ₹0.00 | Net P&L: ₹0.00\n"
                f"Capital: ₹{self.capital_tracker.current_capital:,.2f}"
            )
            self._send(message)
            return

        timestamp_col = pd.to_datetime(df["timestamp_entry"], errors="coerce", utc=True)
        local_dates = timestamp_col.dt.tz_convert(IST).dt.date
        today = now_ist.date()
        today_df = df.loc[local_dates == today].copy()

        if today_df.empty:
            message = (
                f"📊 DAILY SHADOW SUMMARY — {now_ist.strftime('%d %b %Y')}\n"
                "Trades: 0 | Wins: 0 | Losses: 0 | Win Rate: 0%\n"
                "Gross P&L: ₹0.00 | Net P&L: ₹0.00\n"
                f"Capital: ₹{self.capital_tracker.current_capital:,.2f}"
            )
            self._send(message)
            return

        closed = today_df[today_df["timestamp_exit"].notna()].copy()
        total_trades = int(len(today_df))
        if closed.empty:
            wins = 0
            losses = 0
            win_rate = 0.0
            gross_pnl = 0.0
            net_pnl = 0.0
        else:
            gross_series = pd.to_numeric(closed["pnl_gross"], errors="coerce").fillna(0.0)
            net_series = pd.to_numeric(closed["pnl_net"], errors="coerce").fillna(0.0)
            gross_pnl = float(gross_series.sum())
            net_pnl = float(net_series.sum())
            wins = int((net_series > 0).sum())
            losses = int((net_series <= 0).sum())
            win_rate = (wins / len(closed)) if len(closed) else 0.0

        gross_sign = "+" if gross_pnl >= 0 else "-"
        net_sign = "+" if net_pnl >= 0 else "-"
        total_charges = float(
            pd.to_numeric(closed["charges"], errors="coerce").fillna(0.0).sum()
        ) if not closed.empty else 0.0

        lines = [
            f"📊 DAILY SHADOW SUMMARY — {now_ist.strftime('%d %b %Y')}",
            f"Trades: {total_trades} | Wins: {wins} | Losses: {losses} | Win Rate: {int(round(win_rate * 100))}%",
            f"Gross: {gross_sign}₹{abs(gross_pnl):,.2f} | Charges: ₹{total_charges:,.2f} | Net: {net_sign}₹{abs(net_pnl):,.2f}",
            f"Capital: ₹{self.capital_tracker.current_capital:,.2f}",
        ]

        if not closed.empty:
            lines.append("─" * 30)
            for _, t in closed.sort_values("timestamp_entry").iterrows():
                expiry_raw = pd.to_datetime(t.get("expiry_date"), errors="coerce")
                expiry_str = expiry_raw.strftime("%d%b").upper() if not pd.isna(expiry_raw) else "?"
                instrument = str(t.get("instrument", "NIFTY")).upper()
                strike = int(float(t.get("strike", 0)))
                opt = str(t.get("option_type", "?")).upper()
                symbol = f"{instrument}{expiry_str}{strike}{opt}"

                entry_p = float(t.get("entry_premium", 0))
                exit_p = float(t.get("exit_premium", 0))
                pnl = float(pd.to_numeric(t.get("pnl_net"), errors="coerce") or 0.0)
                reason = str(t.get("exit_reason", "?"))
                sign = "+" if pnl >= 0 else "-"
                icon = "✅" if pnl > 0 else "❌"

                entry_ts = pd.to_datetime(t.get("timestamp_entry"), errors="coerce", utc=True)
                exit_ts = pd.to_datetime(t.get("timestamp_exit"), errors="coerce", utc=True)
                entry_time = entry_ts.tz_convert(IST).strftime("%H:%M") if not pd.isna(entry_ts) else "?"
                exit_time = exit_ts.tz_convert(IST).strftime("%H:%M") if not pd.isna(exit_ts) else "?"

                lines.append(
                    f"{icon} {symbol}\n"
                    f"   {entry_time}→{exit_time}  entry=₹{entry_p:.0f}  exit=₹{exit_p:.0f}  {reason}\n"
                    f"   Net: {sign}₹{abs(pnl):,.2f}"
                )

        self._send("\n".join(lines))

    def send_startup_summary(self, instrument: str, started_at: datetime, open_trades: list[dict]) -> None:
        now_ist = datetime.now(IST)
        today = now_ist.date()

        df = self.journal.load_all()
        closed_df = pd.DataFrame()
        if not df.empty:
            exit_ts = pd.to_datetime(df["timestamp_exit"], errors="coerce", utc=True)
            ist_dates = exit_ts.dt.tz_convert(IST).dt.date
            closed_df = df[(ist_dates == today) & df["timestamp_exit"].notna()].copy()

        net_series   = pd.to_numeric(closed_df["pnl_net"],   errors="coerce").fillna(0.0) if not closed_df.empty else pd.Series([], dtype=float)
        gross_series = pd.to_numeric(closed_df["pnl_gross"], errors="coerce").fillna(0.0) if not closed_df.empty else pd.Series([], dtype=float)
        charge_series = pd.to_numeric(closed_df["charges"],  errors="coerce").fillna(0.0) if not closed_df.empty else pd.Series([], dtype=float)

        closed_count = len(closed_df)
        wins         = int((net_series > 0).sum())
        losses       = int((net_series <= 0).sum())
        win_rate     = int(round(wins / closed_count * 100)) if closed_count else 0
        net_pnl      = float(net_series.sum())
        gross_pnl    = float(gross_series.sum())
        total_charges = float(charge_series.sum())
        capital      = self.capital_tracker.current_capital

        def _sign(v: float) -> str: return "+" if v >= 0 else "-"

        lines = [
            f"🔄 AGENT RESTARTED — {instrument}",
            f"🕐 {started_at.strftime('%d %b %Y  %H:%M IST')}",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"📅 TODAY'S PERFORMANCE",
            f"  Trades : {closed_count}  ({wins}W / {losses}L)  {win_rate}% WR",
            f"  Gross  : {_sign(gross_pnl)}₹{abs(gross_pnl):,.2f}",
            f"  Charges: ₹{total_charges:,.2f}",
            f"  Net    : {_sign(net_pnl)}₹{abs(net_pnl):,.2f}",
            f"  Capital: ₹{capital:,.2f}",
        ]

        if not closed_df.empty:
            lines.append(f"─────────────────────────")
            for _, t in closed_df.sort_values("timestamp_entry").iterrows():
                opt      = str(t.get("option_type", "?"))
                strike   = int(float(t.get("strike", 0)))
                instr    = str(t.get("instrument", "NIFTY")).upper()
                expiry   = pd.to_datetime(t.get("expiry_date"), errors="coerce")
                exp_str  = expiry.strftime("%d%b").upper() if not pd.isna(expiry) else "?"
                contract = f"{instr}{exp_str}{strike}{opt}"
                entry    = float(t.get("entry_premium", 0))
                exit_p   = float(t.get("exit_premium", 0))
                pnl      = float(pd.to_numeric(t.get("pnl_net"), errors="coerce") or 0.0)
                reason   = str(t.get("exit_reason", "?"))
                lots_raw = t.get("lots", 1)
                lots     = int(float(lots_raw)) if lots_raw == lots_raw and lots_raw else 1
                icon     = "✅" if pnl > 0 else "❌"
                entry_ts = pd.to_datetime(t.get("timestamp_entry"), errors="coerce", utc=True)
                exit_ts  = pd.to_datetime(t.get("timestamp_exit"),  errors="coerce", utc=True)
                t_in     = entry_ts.tz_convert(IST).strftime("%H:%M") if not pd.isna(entry_ts) else "?"
                t_out    = exit_ts.tz_convert(IST).strftime("%H:%M")  if not pd.isna(exit_ts)  else "?"
                lines.append(
                    f"{icon} {contract}  {t_in}→{t_out}  {lots} lots  ₹{entry:.2f}→₹{exit_p:.2f}  {reason}  {_sign(pnl)}₹{abs(pnl):,.2f}"
                )

        if open_trades:
            lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"♻️ {len(open_trades)} OPEN TRADE(S) RESTORED")
            for t in open_trades:
                opt      = t.get("option_type", "?")
                strike   = t.get("strike", "?")
                instr    = t.get("instrument", "NIFTY")
                expiry   = pd.to_datetime(t.get("expiry_date"), errors="coerce")
                exp_str  = expiry.strftime("%d%b").upper() if not pd.isna(expiry) else "?"
                contract = f"{instr}{exp_str}{strike}{opt}"
                entry    = float(t.get("entry_premium", 0))
                sl       = float(t.get("current_sl", 0))
                tp       = float(t.get("target_price", 0))
                lots_raw = t.get("lots", 1)
                lots     = int(float(lots_raw)) if lots_raw == lots_raw and lots_raw else 1
                conf     = int(round(float(t.get("confidence", 0)) * 100))
                trail    = "🔁 trailing" if t.get("trail_active") else "👀 watching"
                lines.append(
                    f"  {contract}  {lots} lots  conf={conf}%  {trail}\n"
                    f"  entry=₹{entry:.2f}  SL=₹{sl:.2f}  TP=₹{tp:.2f}"
                )
        else:
            lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("📭 No open trades")

        self._send("\n".join(lines))

    def send_daily_target_alert(self, daily_pnl: float) -> None:
        message = (
            f"🎯 DAILY TARGET HIT — ₹{daily_pnl:,.0f} realized\n"
            "Auto-trading paused. New signals need manual verification.\n"
            "Open trades are live — trail is active, let them run."
        )
        self._send(message)

    def send_restored_trades_alert(self, trades: list[dict]) -> None:
        lines = [f"♻️ {len(trades)} OPEN TRADE(S) RESTORED\n"]
        for t in trades:
            opt = t.get("option_type", "?")
            strike = t.get("strike", "?")
            exp = t.get("expiry_date", "")
            entry = float(t.get("entry_premium", 0))
            sl = float(t.get("current_sl", 0))
            lines.append(f"  {opt} {strike}  exp:{exp}  entry:₹{entry:.0f}  SL:₹{sl:.0f}")
        self._send("\n".join(lines))
