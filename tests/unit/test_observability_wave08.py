"""Wave 08 — OBS-019..021 novelty / loops / capacity metrics."""

from __future__ import annotations

import pytest

from telegram_lead_discovery.observability.capacity import (
    CAPACITY_METRIC_NAMES,
    observe_capacity,
    record_burst_backlog_age_seconds,
    record_exact_dedupe_rejected,
    record_ingestion,
    record_received_to_processed_seconds,
    record_restart_recovery_duration_seconds,
    set_monitoring_source_count,
)
from telegram_lead_discovery.observability.discovery import (
    FORBIDDEN_METRIC_LABEL_KEYS,
    NOVELTY_METRIC_NAMES,
    ForbiddenMetricLabelError,
    observe_discovery,
    record_cooldown_suppressed,
    record_dismissed_suppressed,
    record_funnel_observability,
    record_novel_presented,
    record_novelty_ratio,
    record_pool_exhausted,
    record_registry_suppressed,
    reset_discovery_observability,
)
from telegram_lead_discovery.observability.health import HealthState, reset_health_registry
from telegram_lead_discovery.observability.loops import (
    NAMED_RUNTIME_LOOPS,
    apply_named_loop_running_map,
    ensure_named_loop_components,
    named_loop_views,
)
from telegram_lead_discovery.observability.metrics import get_metrics, reset_metrics


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_metrics()
    reset_health_registry()
    reset_discovery_observability()
    yield
    reset_metrics()
    reset_health_registry()
    reset_discovery_observability()


def test_at_obs_019_novelty_metrics_and_forbidden_labels() -> None:
    record_novel_presented(3)
    record_registry_suppressed(2)
    record_dismissed_suppressed(1)
    record_cooldown_suppressed(4)
    record_pool_exhausted(reason="provider_empty")
    record_novelty_ratio(0.5)
    record_funnel_observability(
        {
            "novel_presented_total": 1,
            "registry_suppressed": 1,
            "dismissed_suppressed": 1,
            "cooldown_suppressed": 1,
            "pool_exhausted": 1,
            "pool_exhausted_reason": "budget_cap_reached",
            "presented_total": 2,
        }
    )

    names = {b.metric_name for b in get_metrics().buckets.values()}
    for required in NOVELTY_METRIC_NAMES:
        assert required in names

    for bucket in get_metrics().buckets.values():
        for forbidden in FORBIDDEN_METRIC_LABEL_KEYS:
            assert f"{forbidden}=" not in bucket.labels_key

    with pytest.raises(ForbiddenMetricLabelError):
        observe_discovery(
            "discovery_novel_presented_total",
            labels={"run_id": "9"},
        )
    with pytest.raises(ForbiddenMetricLabelError):
        observe_discovery(
            "discovery_pool_exhausted_total",
            labels={"reason": "x", "username": "leak"},
        )


def test_at_obs_020_named_loops_not_permanent_deferred() -> None:
    registry = ensure_named_loop_components()
    for name in NAMED_RUNTIME_LOOPS:
        assert name in registry.components

    apply_named_loop_running_map(
        {
            "keyword_discovery": True,
            "collector_jobs": False,
            "live_updates": True,
            "processing": True,
            "notifications": True,
            "reconciliation": True,
            "watchdog": True,
        },
        registry=registry,
        credentials_present=True,
        monitoring_source_count=3,
    )
    collector = registry.components["collector_jobs"]
    assert collector.state is not HealthState.STOPPED
    assert collector.state is HealthState.DEGRADED
    assert collector.reason_code == "awaiting_collector_heartbeat"

    views = named_loop_views(registry)
    assert len(views) == len(NAMED_RUNTIME_LOOPS)
    assert {v.name for v in views} == set(NAMED_RUNTIME_LOOPS)


def test_at_obs_021_capacity_metric_names() -> None:
    set_monitoring_source_count(100)
    record_ingestion(10)
    record_burst_backlog_age_seconds(12.5)
    record_received_to_processed_seconds(8.0)
    record_restart_recovery_duration_seconds(45.0)
    record_exact_dedupe_rejected(3)

    names = {b.metric_name for b in get_metrics().buckets.values()}
    for required in CAPACITY_METRIC_NAMES:
        assert required in names

    with pytest.raises(ValueError):
        observe_capacity("not_a_real_metric")
