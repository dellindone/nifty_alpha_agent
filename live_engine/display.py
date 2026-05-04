from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from config.settings import get_instrument_config

logger = logging.getLogger(__name__)


class Display:
    def __init__(self, engine) -> None:
        self._e = engine

    def _print_live_display(self, now_ist: datetime) -> None:
        price = self._e._last_index_price
        time_str = now_ist.strftime("%H:%M:%S IST")
        capital = float(self._e.capital_tracker.current_capital)
        sep = "━" * 63
        thin = "─" * 63
        trade_lines: list[str] = []
        for snap in self._e.shadow_mode.open_trade_display_snapshots():
            opt, stk, expiry_date = snap["option_type"], snap["strike"], snap["expiry_date"]
            exp_label = f"{self._e.instrument}{expiry_date.day:02d}{expiry_date.strftime('%b').upper()}{stk}{opt}" if hasattr(expiry_date, "strftime") else f"{opt}{stk}"
            entry, sl, tp, lot_size, lots = snap["entry_premium"], snap["current_sl"], snap["current_target"], snap["lot_size"], snap["lots"]
            conf, age_s = int(round(snap["confidence"] * 100)), (datetime.now(timezone.utc) - snap["entry_time"]).total_seconds()
            age_str, opt_sym = f"{int(age_s // 60)}m{int(age_s % 60):02d}s", snap.get("option_symbol", "")
            current_prem = self._e._last_current_premiums.get(opt_sym, entry) if opt_sym else entry
            pnl_gross = (current_prem - entry) * lot_size * lots
            pnl_pct = (current_prem - entry) / entry * 100 if entry > 0 else 0.0
            pnl_sign = "+" if pnl_gross >= 0 else ""
            trade_lines.extend([sep, f"  TRADE    {exp_label}   entry=₹{entry:.0f}  now=₹{current_prem:.2f}  SL=₹{sl:.0f}  TP=₹{tp:.0f}  conf={conf}%", f"  UNREALIZ  {pnl_sign}₹{pnl_gross:,.0f}  ({pnl_sign}{pnl_pct:.2f}%)   {lots} lots   age {age_str}"])
        d = self._e._last_pred_data
        if not trade_lines:
            trade_lines = [sep, f"  PROJ  {d['direction']}  entry~₹{self._e._last_current_premiums.get(self._e.instrument, 0):.0f}  SL~₹{d['sl_price']:.0f}  TP~₹{d['target_price']:.0f}" if d.get("direction") and d.get("sl_price", 0) > 0 else "  no signal  ---  watching"]
        model_line = f"  {d.get('direction','?')}  conf={int(d.get('confidence',0)*100)}%  sl_bin={d.get('sl_bin','?')}  trail={d.get('trail_bin','?')}  tf={d.get('trail_tf','?')}" if d else "  ---"
        health_rows: list[str] = []
        check_order = [
            "fyers_websocket",
            "fyers_candle_api",
            "fyers_vix",
            "fyers_option_chain",
            "feature_pipeline",
            "model_predict",
            "broker_api",
            "db_connection",
        ]
        now_utc = datetime.now(timezone.utc)
        for name in check_order:
            chk = self._e.health._checks.get(name)
            if chk is None:
                icon, status_text, age_text = "⚠️", "missing", "n/a"
            else:
                icon = "✅" if chk.status == "ok" else ("⚠️" if chk.status == "warn" else "🔴")
                status_text = str(chk.detail).strip() if str(chk.detail).strip() else "ok"
                age_sec = int(max(0, (now_utc - chk.last_updated).total_seconds()))
                age_text = f"{age_sec}s ago" if age_sec < 60 else f"{age_sec // 60}m {age_sec % 60}s ago"
            short = name[6:] if name.startswith("fyers_") else name
            health_rows.append(f"  {icon} {short[:16]:<16} {status_text}  {age_text}")
        score, overall = self._e.health.score(), self._e.health.overall()
        overall_icon = "✅" if overall == "ok" else ("⚠️" if overall == "warn" else "🔴")
        cfg = get_instrument_config(self._e.instrument)
        day_pnl = self._e._daily_realized_pnl(now_ist.date())
        pnl_sign = "+" if day_pnl >= 0 else ""
        pnl_color = "\033[32m" if day_pnl >= 0 else "\033[31m"
        pnl_reset = "\033[0m"
        model_tag = f"{self._e.predictor.model_name}  {self._e.predictor.model_version}"
        lines = [
            sep,
            f"  {'▲' if price > 0 else '─'}  {self._e.instrument}  {price:>10,.2f}    {time_str}    polls: {self._e._poll_count}",
            f"  VIX  {self._e._last_vix:.1f}   ATR  {self._e._last_atr:.1f}    OPEN  {len(self._e.shadow_mode.open_trades())}    CAP  ₹{capital:,.0f}",
            f"  {model_tag}    target ₹{cfg.daily_target:,}   stop ₹{cfg.daily_loss_limit:,}   day {pnl_color}{pnl_sign}₹{day_pnl:,.0f}{pnl_reset}",
            thin,
            *health_rows,
            f"  SCORE  {score}/100  {overall_icon}  {overall}",
            thin,
            *trade_lines,
            sep,
            f"  MODEL   {model_line}",
            f"  DECISION  {self._e._last_decision}",
            sep,
        ]
        if self._e._display_line_count > 0:
            sys.stdout.write(f"\033[{self._e._display_line_count}A\033[J")
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()
        self._e._display_line_count = len(lines)

    def _log_poll(self, now_ist: datetime, signal_label: str, open_trades_count: int | None = None) -> None:
        count = len(self._e.journal.open_trades()) if open_trades_count is None else int(open_trades_count)
        logger.info("poll timestamp=%s signal=%s open_trades=%d", now_ist.isoformat(), signal_label, count)
