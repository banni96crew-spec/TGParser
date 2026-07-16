"""Unit — observability structured logs and health endpoints."""

from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient

from telegram_lead_discovery.dashboard.app import create_app
from telegram_lead_discovery.observability.health import (
    HealthState,
    ReadinessState,
    reset_health_registry,
)
from telegram_lead_discovery.observability.logging import StructuredJsonFormatter, StructuredLogger


def test_at_obs_004_structured_log_fields() -> None:
    logger = StructuredLogger("OBS_TEST")
    records: list[str] = []

    class ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(self.format(record))

    handler = ListHandler()
    handler.setFormatter(StructuredJsonFormatter())
    logger._logger.addHandler(handler)
    logger.emit(
        level="info",
        event_code="OBS_PROBE",
        event_name="probe",
        correlation_id="corr-1",
        result="ok",
        duration_ms=12,
        fields={"api_hash": "secret", "count": 1},
    )
    assert records
    payload = json.loads(records[-1])
    assert payload["event_name"] == "probe"
    assert payload["event_code"] == "OBS_PROBE"
    assert payload["component"] == "OBS_TEST"
    assert payload["correlation_id"] == "corr-1"
    assert payload["result"] == "ok"
    assert payload["duration_ms"] == 12
    assert "timestamp" in payload
    assert payload["fields"]["api_hash"] == "[REDACTED]"
    assert payload["fields"]["count"] == 1


def test_at_obs_015_live_vs_ready() -> None:
    registry = reset_health_registry()
    app = create_app()
    client = TestClient(app)

    live = client.get("/health/live")
    assert live.status_code == 200
    assert live.json()["status"] in {"live", "alive"}

    ready_fail = client.get("/health/ready")
    assert ready_fail.status_code == 503
    assert ready_fail.json()["status"] == "not_ready"

    registry.migration_ok = True
    registry.integrity_ok = True
    registry.database_ok = True
    registry.mark_ready()
    registry.set_component("runtime", HealthState.HEALTHY)
    assert registry.readiness is ReadinessState.READY

    ready_ok = client.get("/health/ready")
    assert ready_ok.status_code == 200
    assert ready_ok.json()["status"] == "ready"
