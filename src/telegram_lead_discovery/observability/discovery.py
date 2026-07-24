"""Keyword discovery metrics, health, and safe structured logs (OBS-017 / OBS-018).

Metric labels MUST NOT include query text, source title, username, run ID, or
Telegram ID. Logs MAY include run_id and query ordinal but MUST NOT include
excerpts, authors, secrets, or full message text.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from telegram_lead_discovery.observability.health import (
    HealthRegistry,
    HealthState,
    get_health_registry,
)
from telegram_lead_discovery.observability.logging import StructuredLogger
from telegram_lead_discovery.observability.metrics import get_metrics

COMPONENT = "discovery"
LOGGER = StructuredLogger("SRC")

# Forbidden metric label keys (OBS-017 / plan §16). Values may appear in logs only.
FORBIDDEN_METRIC_LABEL_KEYS = frozenset(
    {
        "query",
        "query_text",
        "text",
        "title",
        "source_title",
        "username",
        "source_username",
        "run_id",
        "telegram_id",
        "source_telegram_id",
        "excerpt",
        "author",
        "authors",
    }
)

ALLOWED_DISCOVERY_STATES = frozenset(
    {
        HealthState.HEALTHY,
        HealthState.DEGRADED,
        HealthState.BLOCKED,
        HealthState.STOPPED,
    }
)

# Frequent transient errors within this window mark discovery degraded.
_TRANSIENT_WINDOW = timedelta(minutes=10)
_TRANSIENT_DEGRADE_COUNT = 3

_transient_events: list[datetime] = []


class ForbiddenMetricLabelError(ValueError):
    """Raised when a discovery metric would attach a forbidden label."""


def _validate_labels(labels: dict[str, Any]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in labels.items():
        key_l = str(key).lower()
        if key_l in FORBIDDEN_METRIC_LABEL_KEYS:
            raise ForbiddenMetricLabelError(f"forbidden_metric_label:{key}")
        cleaned[str(key)] = str(value)
    return cleaned


def observe_discovery(
    metric_name: str,
    value: float = 1.0,
    *,
    labels: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> None:
    """Record a discovery metric with forbidden-label enforcement."""
    safe = _validate_labels(labels or {})
    get_metrics().observe(metric_name, value, labels=safe, now=now)


def record_run_total(state: str) -> None:
    observe_discovery("discovery_runs_total", labels={"state": state})


def record_query_total(*, kind: str, outcome: str) -> None:
    observe_discovery(
        "discovery_queries_total",
        labels={"kind": kind, "outcome": outcome},
    )


def record_search_hits(*, kind: str, count: int) -> None:
    if count <= 0:
        return
    observe_discovery(
        "discovery_search_hits_total",
        float(count),
        labels={"kind": kind},
    )


def record_unique_sources(count: int) -> None:
    if count <= 0:
        return
    observe_discovery("discovery_unique_sources_total", float(count))


def record_verified_sources(count: int) -> None:
    if count <= 0:
        return
    observe_discovery("discovery_verified_sources_total", float(count))


def record_qualified_evidence(count: int) -> None:
    if count <= 0:
        return
    observe_discovery("discovery_qualified_evidence_total", float(count))


def record_promotion(*, result: str) -> None:
    observe_discovery("discovery_promotions_total", labels={"result": result})


def record_flood_wait_seconds(seconds: float) -> None:
    observe_discovery("discovery_flood_wait_seconds", max(0.0, float(seconds)))


def record_quota_skipped(count: int = 1) -> None:
    """Quota exhaustion metric only — MUST NOT change discovery health."""
    if count <= 0:
        return
    observe_discovery("discovery_quota_skipped_total", float(count))


def record_run_duration_seconds(seconds: float) -> None:
    observe_discovery("discovery_run_duration_seconds", max(0.0, float(seconds)))


def record_score(*, band: str) -> None:
    observe_discovery("discovery_score_total", labels={"band": band})


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


def log_discovery(
    *,
    event_code: str,
    result: str | None = None,
    duration_ms: int | None = None,
    level: str = "info",
    correlation_id: str | None = None,
    fields: dict[str, Any] | None = None,
) -> None:
    """Emit a discovery structured log with safe context only."""
    safe_fields = _sanitize_log_fields(fields or {})
    LOGGER.emit(
        level=level,
        event_code=event_code,
        event_name=event_code,
        correlation_id=correlation_id,
        result=result,
        duration_ms=duration_ms,
        fields=safe_fields,
    )


_LOG_FORBIDDEN_FIELD_KEYS = frozenset(
    {
        "query_text",
        "query",
        "text",
        "message_text",
        "excerpt",
        "excerpts",
        "author",
        "authors",
        "title",
        "source_title",
        "username",
        "source_username",
        "api_hash",
        "api_id",
        "bot_token",
        "session",
        "secret",
        "raw_exception",
        "exception_message",
    }
)


def _sanitize_log_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Drop sensitive keys; keep run_id / ordinal / method / counts / codes."""
    out: dict[str, Any] = {}
    for key, value in fields.items():
        key_l = str(key).lower()
        if key_l in _LOG_FORBIDDEN_FIELD_KEYS:
            continue
        if key_l.endswith("_text") or key_l.endswith("_excerpt"):
            continue
        out[str(key)] = value
    return out


def log_query_progress(
    *,
    run_id: int,
    query_ordinal: int,
    method: str,
    result_count: int,
    error_code: str | None,
    duration_ms: int | None,
    quota_outcome: str | None = None,
    outcome: str,
) -> None:
    fields: dict[str, Any] = {
        "run_id": run_id,
        "query_ordinal": query_ordinal,
        "method": method,
        "result_count": result_count,
        "outcome": outcome,
    }
    if error_code is not None:
        fields["error_code"] = error_code
    if quota_outcome is not None:
        fields["quota_outcome"] = quota_outcome
    log_discovery(
        event_code="discovery.query_finished",
        result=outcome,
        duration_ms=duration_ms,
        fields=fields,
    )


def log_run_finished(
    *,
    run_id: int,
    state: str,
    duration_ms: int | None,
    error_code: str | None = None,
    evidence_count: int | None = None,
    unique_sources: int | None = None,
) -> None:
    fields: dict[str, Any] = {"run_id": run_id, "state": state}
    if error_code is not None:
        fields["error_code"] = error_code
    if evidence_count is not None:
        fields["evidence_count"] = evidence_count
    if unique_sources is not None:
        fields["unique_sources"] = unique_sources
    log_discovery(
        event_code="discovery.run_finished",
        result=state,
        duration_ms=duration_ms,
        level="error" if state == "failed" else "info",
        fields=fields,
    )


__all__ = [
    "ALLOWED_DISCOVERY_STATES",
    "COMPONENT",
    "FORBIDDEN_METRIC_LABEL_KEYS",
    "ForbiddenMetricLabelError",
    "log_discovery",
    "log_query_progress",
    "log_run_finished",
    "mark_discovery_blocked",
    "mark_discovery_degraded",
    "mark_discovery_healthy",
    "mark_discovery_stopped",
    "note_flood_wait",
    "note_quota_skipped",
    "note_run_recovered",
    "note_session_fatal",
    "note_transient_error",
    "observe_discovery",
    "record_flood_wait_seconds",
    "record_promotion",
    "record_qualified_evidence",
    "record_query_total",
    "record_run_duration_seconds",
    "record_run_total",
    "record_score",
    "record_search_hits",
    "record_unique_sources",
    "record_verified_sources",
    "reset_discovery_observability",
    "set_discovery_health",
]
