import logging

from health import AgentHealth, HealthStatus

logger = logging.getLogger(__name__)
_RANK = {"ok": 0, "warn": 1, "critical": 2}


class HealthMonitor:
    def __init__(self, health: AgentHealth, reporter) -> None:
        self._health = health
        self._reporter = reporter
        self._last_overall: HealthStatus = "ok"

    def _send(self, message: str) -> None:
        self._reporter.send_health_alert(message)

    def check_and_alert(self) -> None:
        current, previous, score = self._health.overall(), self._last_overall, self._health.score()
        if current == previous:
            return
        logger.warning("health transition %s→%s score=%d", previous, current, score)
        if _RANK[current] > _RANK[previous]:
            checks = self._health.checks_in_state("critical" if current == "critical" else "warn") or self._health.checks_in_state("critical")
            label = "CRITICAL" if current == "critical" else "DEGRADED"
            icon = "🔴" if current == "critical" else "⚠️"
            items = ", ".join(f"{c.name} ({c.detail})".strip() for c in checks) or "unknown"
            prefix = "Critical" if current == "critical" else "Degraded"
            self._send(f"{icon} NIFTY AGENT HEALTH {label} — Score: {score}/100\n{prefix} checks: {items}")
        else:
            self._send(f"✅ NIFTY AGENT HEALTH RECOVERED — Score: {score}/100\nAll systems operational")
        self._last_overall = current
