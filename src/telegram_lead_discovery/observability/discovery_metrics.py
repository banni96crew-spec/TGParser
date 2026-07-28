"""Keyword-discovery metrics."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from telegram_lead_discovery.observability.metrics import get_metrics

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


NOVELTY_METRIC_NAMES: frozenset[str] = frozenset(
    {
        "discovery_novel_presented_total",
        "discovery_registry_suppressed_total",
        "discovery_dismissed_suppressed_total",
        "discovery_cooldown_suppressed_total",
        "discovery_pool_exhausted_total",
        "discovery_novelty_ratio",
    }
)


def record_novel_presented(count: int = 1) -> None:
    if count <= 0:
        return
    observe_discovery("discovery_novel_presented_total", float(count))


def record_registry_suppressed(count: int = 1) -> None:
    if count <= 0:
        return
    observe_discovery("discovery_registry_suppressed_total", float(count))


def record_dismissed_suppressed(count: int = 1) -> None:
    if count <= 0:
        return
    observe_discovery("discovery_dismissed_suppressed_total", float(count))


def record_cooldown_suppressed(count: int = 1) -> None:
    if count <= 0:
        return
    observe_discovery("discovery_cooldown_suppressed_total", float(count))


def record_pool_exhausted(*, reason: str) -> None:
    """reason is a closed SRC-038 code — never query text or source identity."""
    safe_reason = (reason or "unknown").strip()[:64] or "unknown"
    observe_discovery(
        "discovery_pool_exhausted_total",
        labels={"reason": safe_reason},
    )


def record_novelty_ratio(ratio: float) -> None:
    """Store novelty ratio as 0..1 float (UI may show bp/10000 from run counters)."""
    observe_discovery("discovery_novelty_ratio", max(0.0, min(1.0, float(ratio))))


def record_funnel_observability(counters: dict[str, Any]) -> None:
    """Publish OBS-019 metrics from a run counters dict (idempotent per call)."""
    novel = int(counters.get("novel_presented_total") or 0)
    if novel:
        record_novel_presented(novel)
    reg = int(counters.get("registry_suppressed") or 0)
    if reg:
        record_registry_suppressed(reg)
    dismissed = int(counters.get("dismissed_suppressed") or 0)
    if dismissed:
        record_dismissed_suppressed(dismissed)
    cooldown = int(
        counters.get("presented_suppressed") or counters.get("cooldown_suppressed") or 0
    )
    if cooldown:
        record_cooldown_suppressed(cooldown)
    if int(counters.get("pool_exhausted") or 0):
        reason = counters.get("pool_exhausted_reason")
        if not isinstance(reason, str) or not reason:
            code = counters.get("pool_exhausted_reason_code")
            reason = f"code_{code}" if code is not None else "unknown"
        record_pool_exhausted(reason=str(reason))
    presented = int(counters.get("presented_total") or 0)
    if presented > 0:
        record_novelty_ratio(novel / presented)
    elif "novelty_ratio_bp" in counters:
        record_novelty_ratio(int(counters["novelty_ratio_bp"]) / 10000.0)
