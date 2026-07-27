"""Named runtime loop health (OBS-020 / INF-022 / D-066)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from telegram_lead_discovery.observability.health import (
    HealthRegistry,
    HealthState,
    get_health_registry,
)

# Canonical INF-022 loop names exposed to health UI / readiness.
NAMED_RUNTIME_LOOPS: tuple[str, ...] = (
    "discovery_claim",
    "collector_jobs",
    "live_updates",
    "processing_claim",
    "notification_outbox",
    "reconciliation",
    "health_watchdog",
)

# Map DiscoveryCoordinator.named_loops_running() keys → OBS-020 names.
RUNTIME_LOOP_ALIASES: dict[str, str] = {
    "keyword_discovery": "discovery_claim",
    "graph_discovery": "discovery_claim",
    "collector_jobs": "collector_jobs",
    "live_updates": "live_updates",
    "processing": "processing_claim",
    "notifications": "notification_outbox",
    "reconciliation": "reconciliation",
    "watchdog": "health_watchdog",
}


@dataclass(frozen=True, slots=True)
class LoopHealthView:
    name: str
    state: str
    reason_code: str | None
    heartbeat_at: datetime | None = None


def ensure_named_loop_components(
    registry: HealthRegistry | None = None,
    *,
    default: HealthState = HealthState.STARTING,
) -> HealthRegistry:
    """Register all named loops so UI never shows an empty health matrix."""
    target = registry if registry is not None else get_health_registry()
    for name in NAMED_RUNTIME_LOOPS:
        if name not in target.components:
            target.set_component(name, default, reason_code="awaiting_start")
    return target


def set_loop_health(
    loop_name: str,
    state: HealthState,
    *,
    reason_code: str | None = None,
    registry: HealthRegistry | None = None,
) -> None:
    if loop_name not in NAMED_RUNTIME_LOOPS:
        raise ValueError(f"unknown_runtime_loop:{loop_name}")
    target = registry if registry is not None else get_health_registry()
    target.set_component(loop_name, state, reason_code=reason_code)


def apply_named_loop_running_map(
    running: Mapping[str, bool],
    *,
    registry: HealthRegistry | None = None,
    credentials_present: bool = False,
    monitoring_source_count: int = 0,
) -> None:
    """Project coordinator running flags onto OBS-020 loop components.

    Collector MUST NOT stay permanent STOPPED/deferred when credentials and
    monitoring sources exist (D-066 / OBS-020).
    """
    target = ensure_named_loop_components(registry)
    aggregated: dict[str, bool] = {name: False for name in NAMED_RUNTIME_LOOPS}
    for raw_name, is_running in running.items():
        obs_name = RUNTIME_LOOP_ALIASES.get(raw_name, raw_name)
        if obs_name not in aggregated:
            continue
        aggregated[obs_name] = aggregated[obs_name] or bool(is_running)

    for name, is_running in aggregated.items():
        if is_running:
            set_loop_health(name, HealthState.HEALTHY, reason_code="heartbeat", registry=target)
            continue
        if name == "collector_jobs" and credentials_present and monitoring_source_count > 0:
            # Not permanent deferred — mark degraded until first beat.
            set_loop_health(
                name,
                HealthState.DEGRADED,
                reason_code="awaiting_collector_heartbeat",
                registry=target,
            )
            continue
        if name in {"discovery_claim", "live_updates"} and not credentials_present:
            set_loop_health(
                name,
                HealthState.BLOCKED,
                reason_code="credentials_missing",
                registry=target,
            )
            continue
        set_loop_health(
            name,
            HealthState.STOPPED,
            reason_code="loop_not_running",
            registry=target,
        )


def named_loop_views(
    registry: HealthRegistry | None = None,
    *,
    heartbeats: Mapping[str, datetime] | None = None,
) -> list[LoopHealthView]:
    target = ensure_named_loop_components(registry)
    beats = heartbeats or {}
    views: list[LoopHealthView] = []
    for name in NAMED_RUNTIME_LOOPS:
        status = target.components.get(name)
        views.append(
            LoopHealthView(
                name=name,
                state=status.state.value if status else HealthState.STARTING.value,
                reason_code=status.reason_code if status else None,
                heartbeat_at=beats.get(name),
            )
        )
    return views


def utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "NAMED_RUNTIME_LOOPS",
    "RUNTIME_LOOP_ALIASES",
    "LoopHealthView",
    "apply_named_loop_running_map",
    "ensure_named_loop_components",
    "named_loop_views",
    "set_loop_health",
    "utc_now",
]
