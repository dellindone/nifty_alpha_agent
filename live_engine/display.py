from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class Display:
    def __init__(self, engine) -> None:
        self._e = engine

    def _print_live_display(self, now_ist: datetime) -> None:
        price = self._e._last_index_price
        time_str = now_ist.strftime("%H:%M:%S IST")
        capital = float(self._e.capital_tracker.current_capital)
        sep = "━" * 63
        score, overall = self._e.health.score(), self._e.health.overall()
        bad = self._e.health.checks_in_state("warn") + self._e.health.checks_in_state("critical")
        names = "  ".join((("⚠️" if c.status == "warn" else "🔴") + " " + c.name.replace("fyers_websocket", "fyers_ws")) for c in bad)
        health_line = f"  HEALTH  {score} {'✅' if overall == 'ok' else '⚠️' if overall == 'warn' else '🔴'}" + (f"  │  {names}" if names else "")
        trade_lines: list[str] = []
        for snap in self._e.shadow_mode.open_trade_display_snapshots():
            opt, stk, expiry_date = snap["option_type"], snap["strike"], snap["expiry_date"]
            exp_label = f"{self._e.instrument}{expiry_date.day:02d}{expiry_date.strftime('%b').upper()}{stk}{opt}" if hasattr(expiry_date, "strftime") else f"{opt}{stk}"
            entry, sl, tp, lot_size, lots = snap["entry_premium"], snap["current_sl"], snap["current_target"], snap["lot_size"], snap["lots"]
            conf, age_s = int(round(snap["confidence"] * 100)), (datetime.now(timezone.utc) - snap["entry_time"]).total_seconds()
            age_str, opt_sym = f"{int(age_s // 60)}m{int(age_s % 60):02d}s", snap.get("option_symbol", "")
            current_prem = self._e._last_current_premiums[opt_sym] if opt_sym and opt_sym in self._e._last_current_premiums else self._e._last_current_premiums.get(self._e.instrument, entry)
            pnl_gross = (current_prem - entry) * lot_size * lots
            pnl_pct = (current_prem - entry) / entry * 100 if entry > 0 else 0.0
            pnl_sign = "+" if pnl_gross >= 0 else ""
            trade_lines.extend([sep, f"  TRADE    {exp_label}   entry=₹{entry:.0f}  now=₹{current_prem:.2f}  SL=₹{sl:.0f}  TP=₹{tp:.0f}  conf={conf}%", f"  UNREALIZ  {pnl_sign}₹{pnl_gross:,.0f}  ({pnl_sign}{pnl_pct:.2f}%)   {lots} lots   age {age_str}"])
        d = self._e._last_pred_data
        if not trade_lines:
            trade_lines = [sep, f"  PROJ  {d['direction']}  entry~₹{self._e._last_current_premiums.get(self._e.instrument, 0):.0f}  SL~₹{d['sl_price']:.0f}  TP~₹{d['target_price']:.0f}" if d.get("direction") and d.get("sl_price", 0) > 0 else "  no signal  ---  watching"]
        model_line = f"  {d.get('direction','?')}  conf={int(d.get('confidence',0)*100)}%  sl_bin={d.get('sl_bin','?')}  trail={d.get('trail_bin','?')}  tf={d.get('trail_tf','?')}" if d else "  ---"
        lines = [sep, f"  {'▲' if price > 0 else '─'}  {self._e.instrument}  {price:>10,.2f}    {time_str}    polls: {self._e._poll_count}", f"  VIX  {self._e._last_vix:.1f}   ATR  {self._e._last_atr:.1f}    OPEN  {len(self._e.shadow_mode.open_trades())}    CAP  ₹{capital:,.0f}", health_line, *trade_lines, sep, f"  MODEL   {model_line}", f"  DECISION  {self._e._last_decision}", sep]
        if self._e._display_line_count > 0:
            sys.stdout.write(f"\033[{self._e._display_line_count}A\033[J")
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()
        self._e._display_line_count = len(lines)

    def _log_poll(self, now_ist: datetime, signal_label: str, open_trades_count: int | None = None) -> None:
        count = len(self._e.journal.open_trades()) if open_trades_count is None else int(open_trades_count)
        logger.info("poll timestamp=%s signal=%s open_trades=%d", now_ist.isoformat(), signal_label, count)
