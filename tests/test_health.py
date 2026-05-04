from sqlalchemy import create_engine

from db import check_db_health
from health import AgentHealth
from health_monitor import HealthMonitor


class FakeReporter:
    def __init__(self):
        self.messages = []

    def send_health_alert(self, message: str) -> None:
        self.messages.append(message)


class BadEngine:
    def connect(self):
        raise RuntimeError("boom")


def test_score_and_thresholds():
    h = AgentHealth()
    assert h.score() == 100 and h.overall() == "ok"
    h.update("fyers_websocket", "critical", "down")
    assert h.score() == 80 and h.overall() == "ok"
    h.update("fyers_candle_api", "critical", "down")
    assert h.score() == 65 and h.overall() == "warn"
    h.update("fyers_option_chain", "critical", "down")
    assert h.score() == 55 and h.overall() == "critical"


def test_monitor_transitions_and_recovery():
    h, r = AgentHealth(), FakeReporter()
    m = HealthMonitor(h, r)
    h.update("fyers_candle_api", "warn", "HTTP 503")
    h.update("feature_pipeline", "warn", "NaN")
    m.check_and_alert()
    h.update("fyers_candle_api", "warn", "HTTP 503")
    h.update("feature_pipeline", "warn", "NaN")
    m.check_and_alert()
    h.update("fyers_websocket", "critical", "no ticks")
    h.update("feature_pipeline", "critical", "NaN")
    m.check_and_alert()
    h.update("fyers_candle_api", "ok", "")
    h.update("fyers_websocket", "ok", "")
    h.update("feature_pipeline", "ok", "")
    m.check_and_alert()
    assert "DEGRADED" in r.messages[0] and "CRITICAL" in r.messages[1] and "RECOVERED" in r.messages[2]


def test_db_health_states():
    engine = create_engine("sqlite:///:memory:", future=True)
    assert check_db_health(engine) == ("ok", "")
    assert check_db_health(None) == ("warn", "no DB engine (parquet-only mode)")
    status, detail = check_db_health(BadEngine())
    assert status == "critical" and "boom" in detail


def test_status_lines_format():
    h = AgentHealth()
    h.update("fyers_candle_api", "warn", "HTTP 503")
    h.update("model_predict", "ok", "")
    lines = h.status_lines()
    text = "\n".join(lines)
    assert isinstance(lines, list) and len(lines) > 0
    assert "fyers_candle_api" in text
    assert "warn" in text.lower() or "⚠" in text or "503" in text
