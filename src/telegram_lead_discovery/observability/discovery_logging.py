"""Safe structured logs for keyword discovery."""

from __future__ import annotations

from typing import Any

from telegram_lead_discovery.observability.logging import StructuredLogger

LOGGER = StructuredLogger("SRC")


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
