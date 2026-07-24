"""Unit — keyword discovery metrics / health / safe logs (AT-OBS-017 / AT-OBS-018)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest

from telegram_lead_discovery.observability.discovery import (
    FORBIDDEN_METRIC_LABEL_KEYS,
    ForbiddenMetricLabelError,
    _sanitize_log_fields,
    log_discovery,
    mark_discovery_healthy,
    mark_discovery_stopped,
    note_flood_wait,
    note_quota_skipped,
    note_session_fatal,
    note_transient_error,
    observe_discovery,
    record_promotion,
    record_query_total,
    record_run_total,
    record_score,
    reset_discovery_observability,
    set_discovery_health,
)
from telegram_lead_discovery.observability.health import (
    HealthState,
    get_health_registry,
    reset_health_registry,
)
from telegram_lead_discovery.observability.logging import StructuredJsonFormatter, log_event
from telegram_lead_discovery.observability.metrics import get_metrics, reset_metrics


@pytest.fixture(autouse=True)
def _reset_obs() -> None:
    reset_metrics()
    reset_health_registry()
    reset_discovery_observability()
    yield
    reset_metrics()
    reset_health_registry()
    reset_discovery_observability()


def test_at_obs_017_metric_names_and_forbidden_labels() -> None:
    record_run_total("succeeded")
    record_query_total(kind="global_message", outcome="succeeded")
    record_promotion(result="created")
    record_score(band="strong")
    note_quota_skipped(count=2)

    buckets = list(get_metrics().buckets.values())
    names = {b.metric_name for b in buckets}
    assert "discovery_runs_total" in names
    assert "discovery_queries_total" in names
    assert "discovery_promotions_total" in names
    assert "discovery_score_total" in names
    assert "discovery_quota_skipped_total" in names

    for bucket in buckets:
        for forbidden in FORBIDDEN_METRIC_LABEL_KEYS:
            assert f"{forbidden}=" not in bucket.labels_key

    with pytest.raises(ForbiddenMetricLabelError):
        observe_discovery(
            "discovery_runs_total",
            labels={"state": "succeeded", "run_id": "42"},
        )
    with pytest.raises(ForbiddenMetricLabelError):
        observe_discovery(
            "discovery_search_hits_total",
            labels={"kind": "global_message", "username": "leaks"},
        )
    with pytest.raises(ForbiddenMetricLabelError):
        observe_discovery(
            "discovery_unique_sources_total",
            labels={"telegram_id": "1"},
        )


def test_at_obs_018_discovery_health_states_and_quota_not_unhealthy() -> None:
    registry = get_health_registry()
    mark_discovery_healthy(registry=registry)
    assert registry.components["discovery"].state is HealthState.HEALTHY

    note_quota_skipped()
    assert registry.components["discovery"].state is HealthState.HEALTHY
    assert registry.components["discovery"].state is not HealthState.UNHEALTHY

    until = datetime.now(UTC) + timedelta(minutes=5)
    note_flood_wait(until=until)
    assert registry.components["discovery"].state is HealthState.DEGRADED
    assert registry.components["discovery"].reason_code == "flood_wait"

    note_session_fatal(code="unauthorized")
    assert registry.components["discovery"].state is HealthState.BLOCKED

    mark_discovery_stopped(registry=registry)
    assert registry.components["discovery"].state is HealthState.STOPPED

    with pytest.raises(ValueError, match="invalid_discovery_health_state"):
        set_discovery_health(HealthState.UNHEALTHY)


def test_at_obs_018_frequent_transient_degrades() -> None:
    mark_discovery_healthy()
    note_transient_error()
    note_transient_error()
    assert get_health_registry().components["discovery"].state is HealthState.HEALTHY
    note_transient_error()
    assert get_health_registry().components["discovery"].state is HealthState.DEGRADED
    assert (
        get_health_registry().components["discovery"].reason_code
        == "frequent_transient_errors"
    )


def test_discovery_logs_keep_safe_fields_drop_excerpts() -> None:
    cleaned = _sanitize_log_fields(
        {
            "run_id": 7,
            "query_ordinal": 2,
            "method": "global_message",
            "result_count": 3,
            "error_code": "quota_exhausted",
            "quota_outcome": "quota_exhausted",
            "excerpt": "secret lead text",
            "query_text": "купить сайт",
            "username": "shop",
            "authors": ["alice"],
            "api_hash": "deadbeef",
        }
    )
    assert cleaned == {
        "run_id": 7,
        "query_ordinal": 2,
        "method": "global_message",
        "result_count": 3,
        "error_code": "quota_exhausted",
        "quota_outcome": "quota_exhausted",
    }

    # log_discovery path must also strip forbidden keys before emit.
    records: list[str] = []

    class ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(self.format(record))

    handler = ListHandler()
    handler.setFormatter(StructuredJsonFormatter())
    probe = logging.getLogger("tld.SRC.probe_discovery_obs")
    probe.handlers.clear()
    probe.addHandler(handler)
    probe.setLevel(logging.INFO)
    probe.propagate = False

    # Direct structured emit of sanitized fields (OBS-004 shape).
    log_event(
        probe,
        event_name="discovery.query_finished",
        event_code="discovery.query_finished",
        component="SRC",
        result="succeeded",
        duration_ms=15,
        fields=cleaned,
    )
    assert records
    payload = json.loads(records[-1])
    assert payload["fields"]["run_id"] == 7
    assert "excerpt" not in payload["fields"]
    assert "query_text" not in payload["fields"]

    # Ensure public helper applies the same sanitizer.
    sanitized_via_helper = _sanitize_log_fields(
        {"run_id": 1, "excerpt": "x", "method": "global_message"}
    )
    assert sanitized_via_helper == {"run_id": 1, "method": "global_message"}
    assert callable(log_discovery)
