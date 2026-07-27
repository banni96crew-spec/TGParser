"""Capacity / latency / recovery metrics (OBS-021 / NFR-PERF-006..008 / NFR-REL-008)."""

from __future__ import annotations

from typing import Any

from telegram_lead_discovery.observability.metrics import get_metrics

# Approved metric names (OBS-021). Labels MUST stay free of secrets / identities.
CAPACITY_METRIC_NAMES: frozenset[str] = frozenset(
    {
        "monitoring_source_count",
        "ingestion_messages_total",
        "burst_backlog_age_seconds",
        "received_to_processed_seconds",
        "restart_recovery_duration_seconds",
        "exact_dedupe_rejected_total",
    }
)


def observe_capacity(
    metric_name: str,
    value: float = 1.0,
    *,
    labels: dict[str, Any] | None = None,
) -> None:
    if metric_name not in CAPACITY_METRIC_NAMES:
        raise ValueError(f"unknown_capacity_metric:{metric_name}")
    get_metrics().observe(metric_name, value, labels=labels or {})


def set_monitoring_source_count(count: int) -> None:
    observe_capacity("monitoring_source_count", float(max(0, count)))


def record_ingestion(count: int = 1) -> None:
    if count <= 0:
        return
    observe_capacity("ingestion_messages_total", float(count))


def record_burst_backlog_age_seconds(seconds: float) -> None:
    observe_capacity("burst_backlog_age_seconds", max(0.0, float(seconds)))


def record_received_to_processed_seconds(seconds: float) -> None:
    observe_capacity("received_to_processed_seconds", max(0.0, float(seconds)))


def record_restart_recovery_duration_seconds(seconds: float) -> None:
    observe_capacity("restart_recovery_duration_seconds", max(0.0, float(seconds)))


def record_exact_dedupe_rejected(count: int = 1) -> None:
    if count <= 0:
        return
    observe_capacity("exact_dedupe_rejected_total", float(count))


__all__ = [
    "CAPACITY_METRIC_NAMES",
    "observe_capacity",
    "record_burst_backlog_age_seconds",
    "record_exact_dedupe_rejected",
    "record_ingestion",
    "record_received_to_processed_seconds",
    "record_restart_recovery_duration_seconds",
    "set_monitoring_source_count",
]
