from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

HealthStatus = Literal["ok", "warn", "critical"]
_DEFAULTS = {"fyers_websocket": 20, "fyers_candle_api": 15, "fyers_vix": 10, "fyers_option_chain": 10, "feature_pipeline": 15, "model_predict": 10, "broker_api": 15, "db_connection": 5}


@dataclass
class HealthCheck:
    name: str
    status: HealthStatus = "ok"
    detail: str = ""
    weight: int = 10
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AgentHealth:
    def __init__(self) -> None:
        self._checks = {k: HealthCheck(name=k, weight=v) for k, v in _DEFAULTS.items()}

    def update(self, name: str, status: HealthStatus, detail: str) -> None:
        check = self._checks.setdefault(name, HealthCheck(name=name))
        check.status, check.detail, check.last_updated = status, str(detail or ""), datetime.now(timezone.utc)

    def score(self) -> int:
        return int(sum(c.weight for c in self._checks.values() if c.status == "ok"))

    def overall(self) -> HealthStatus:
        score = self.score()
        return "ok" if score >= 80 else "warn" if score >= 60 else "critical"

    def status_lines(self) -> list[str]:
        icons = {"ok": "✅", "warn": "⚠️", "critical": "🔴"}
        return [f"{icons[c.status]} {c.name} {c.detail}".strip() for c in self._checks.values()]

    def checks_in_state(self, status: HealthStatus) -> list[HealthCheck]:
        return [c for c in self._checks.values() if c.status == status]
