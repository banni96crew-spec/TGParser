"""Component health registry and readiness (OBS-015)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class HealthState(StrEnum):
    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    UNHEALTHY = "unhealthy"
    STOPPED = "stopped"


class ReadinessState(StrEnum):
    STARTING = "starting"
    READY = "ready"
    NOT_READY = "not_ready"


@dataclass
class ComponentStatus:
    component: str
    state: HealthState
    reason_code: str | None = None
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class HealthRegistry:
    components: dict[str, ComponentStatus] = field(default_factory=dict)
    readiness: ReadinessState = ReadinessState.STARTING
    migration_ok: bool = False
    integrity_ok: bool = False
    database_ok: bool = False

    def set_component(
        self, component: str, state: HealthState, *, reason_code: str | None = None
    ) -> None:
        self.components[component] = ComponentStatus(
            component=component,
            state=state,
            reason_code=reason_code,
        )

    def mark_ready(self) -> None:
        if self.migration_ok and self.integrity_ok and self.database_ok:
            self.readiness = ReadinessState.READY
        else:
            self.readiness = ReadinessState.NOT_READY

    def live_payload(self) -> dict[str, object]:
        return {"status": "live"}

    def ready_payload(self) -> dict[str, object]:
        ok = self.readiness is ReadinessState.READY
        return {
            "status": "ready" if ok else "not_ready",
            "migration_ok": self.migration_ok,
            "integrity_ok": self.integrity_ok,
            "database_ok": self.database_ok,
        }


_registry = HealthRegistry()


def get_health_registry() -> HealthRegistry:
    return _registry


def reset_health_registry() -> HealthRegistry:
    global _registry
    _registry = HealthRegistry()
    return _registry
