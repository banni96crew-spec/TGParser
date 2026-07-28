"""Compatibility facade for discovery metrics, health, and safe logs."""

from telegram_lead_discovery.observability import discovery_health as _health
from telegram_lead_discovery.observability import discovery_logging as _logging
from telegram_lead_discovery.observability import discovery_metrics as _metrics

COMPONENT = _health.COMPONENT
ALLOWED_DISCOVERY_STATES = _health.ALLOWED_DISCOVERY_STATES
set_discovery_health = _health.set_discovery_health
mark_discovery_healthy = _health.mark_discovery_healthy
mark_discovery_degraded = _health.mark_discovery_degraded
mark_discovery_blocked = _health.mark_discovery_blocked
mark_discovery_stopped = _health.mark_discovery_stopped
note_quota_skipped = _health.note_quota_skipped
note_flood_wait = _health.note_flood_wait
note_transient_error = _health.note_transient_error
note_session_fatal = _health.note_session_fatal
note_run_recovered = _health.note_run_recovered
reset_discovery_observability = _health.reset_discovery_observability

LOGGER = _logging.LOGGER
log_discovery = _logging.log_discovery
_LOG_FORBIDDEN_FIELD_KEYS = _logging._LOG_FORBIDDEN_FIELD_KEYS
_sanitize_log_fields = _logging._sanitize_log_fields
log_query_progress = _logging.log_query_progress
log_run_finished = _logging.log_run_finished

FORBIDDEN_METRIC_LABEL_KEYS = _metrics.FORBIDDEN_METRIC_LABEL_KEYS
NOVELTY_METRIC_NAMES = _metrics.NOVELTY_METRIC_NAMES
ForbiddenMetricLabelError = _metrics.ForbiddenMetricLabelError
_validate_labels = _metrics._validate_labels
observe_discovery = _metrics.observe_discovery
record_run_total = _metrics.record_run_total
record_query_total = _metrics.record_query_total
record_search_hits = _metrics.record_search_hits
record_unique_sources = _metrics.record_unique_sources
record_verified_sources = _metrics.record_verified_sources
record_qualified_evidence = _metrics.record_qualified_evidence
record_promotion = _metrics.record_promotion
record_flood_wait_seconds = _metrics.record_flood_wait_seconds
record_quota_skipped = _metrics.record_quota_skipped
record_run_duration_seconds = _metrics.record_run_duration_seconds
record_score = _metrics.record_score
record_novel_presented = _metrics.record_novel_presented
record_registry_suppressed = _metrics.record_registry_suppressed
record_dismissed_suppressed = _metrics.record_dismissed_suppressed
record_cooldown_suppressed = _metrics.record_cooldown_suppressed
record_pool_exhausted = _metrics.record_pool_exhausted
record_novelty_ratio = _metrics.record_novelty_ratio
record_funnel_observability = _metrics.record_funnel_observability

__all__ = [
    "ALLOWED_DISCOVERY_STATES",
    "COMPONENT",
    "FORBIDDEN_METRIC_LABEL_KEYS",
    "NOVELTY_METRIC_NAMES",
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
    "record_cooldown_suppressed",
    "record_dismissed_suppressed",
    "record_flood_wait_seconds",
    "record_funnel_observability",
    "record_novel_presented",
    "record_novelty_ratio",
    "record_pool_exhausted",
    "record_promotion",
    "record_qualified_evidence",
    "record_query_total",
    "record_registry_suppressed",
    "record_run_duration_seconds",
    "record_run_total",
    "record_score",
    "record_search_hits",
    "record_unique_sources",
    "record_verified_sources",
    "reset_discovery_observability",
    "set_discovery_health",
]
