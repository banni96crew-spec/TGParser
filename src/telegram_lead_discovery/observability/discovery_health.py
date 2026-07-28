"""Keyword-discovery health state."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from telegram_lead_discovery.observability.discovery_metrics import (
    record_flood_wait_seconds,
    record_quota_skipped,
)
from telegram_lead_discovery.observability.health import (
    HealthRegistry,
    HealthState,
    get_health_registry,
)

COMPONENT = "discovery"
ALLOWED_DISCOVERY_STATES = frozenset(
    {
        HealthState.HEALTHY,
        HealthState.DEGRADED,
        HealthState.BLOCKED,
        HealthState.STOPPED,
    }
)
_TRANSIENT_WINDOW = timedelta(minutes=10)
_TRANSIENT_DEGRADE_COUNT = 3
_transient_events: list[datetime] = []


def set_discovery_health(
    state: HealthState,
    *,
    reason_code: str | None = None,
    registry: HealthRegistry | None = None,
) -> None:
    if state not in ALLOWED_DISCOVERY_STATES:
        raise ValueError(f"invalid_discovery_health_state:{state}")
    target = registry if registry is not None else get_health_registry()
    target.set_component(
        COMPONENT,
        state,
        reason_code=reason_code,
    )


def mark_discovery_healthy(
    *,
    reason_code: str | None = None,
    registry: HealthRegistry | None = None,
) -> None:
    set_discovery_health(HealthState.HEALTHY, reason_code=reason_code, registry=registry)


def mark_discovery_degraded(
    *,
    reason_code: str,
    registry: HealthRegistry | None = None,
) -> None:
    set_discovery_health(HealthState.DEGRADED, reason_code=reason_code, registry=registry)


def mark_discovery_blocked(
    *,
    reason_code: str,
    registry: HealthRegistry | None = None,
) -> None:
    set_discovery_health(HealthState.BLOCKED, reason_code=reason_code, registry=registry)


def mark_discovery_stopped(
    *,
    reason_code: str | None = "worker_stopped",
    registry: HealthRegistry | None = None,
) -> None:
    set_discovery_health(HealthState.STOPPED, reason_code=reason_code, registry=registry)


def note_quota_skipped(*, count: int = 1) -> None:
    """Record quota skip without marking discovery unhealthy (OBS-018)."""
    record_quota_skipped(count)


def note_flood_wait(*, until: datetime, now: datetime | None = None) -> None:
    clock = now or datetime.now(UTC)
    until_utc = until if until.tzinfo else until.replace(tzinfo=UTC)
    seconds = max(0.0, (until_utc - clock).total_seconds())
    record_flood_wait_seconds(seconds)
    mark_discovery_degraded(reason_code="flood_wait")


def note_transient_error(*, now: datetime | None = None) -> None:
    clock = now or datetime.now(UTC)
    cutoff = clock - _TRANSIENT_WINDOW
    global _transient_events
    _transient_events = [ts for ts in _transient_events if ts >= cutoff]
    _transient_events.append(clock)
    if len(_transient_events) >= _TRANSIENT_DEGRADE_COUNT:
        mark_discovery_degraded(reason_code="frequent_transient_errors")


def note_session_fatal(*, code: str) -> None:
    mark_discovery_blocked(reason_code=code)


def note_run_recovered() -> None:
    """Clear flood/transient degraded state after a terminal run (worker still up)."""
    status = get_health_registry().components.get(COMPONENT)
    if status is None:
        mark_discovery_healthy()
        return
    if status.state is HealthState.DEGRADED:
        mark_discovery_healthy(reason_code="run_recovered")


def reset_discovery_observability() -> None:
    """Test helper: clear transient-error window state."""
    global _transient_events
    _transient_events = []
