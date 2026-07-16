"""Structured JSON logging with redaction (OBS-004 / OBS-005)."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from telegram_lead_discovery.security.redaction import redact_event


class StructuredJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "event_name": getattr(record, "event_name", record.getMessage()),
            "event_code": getattr(record, "event_code", None),
            "component": getattr(record, "component", record.name),
            "correlation_id": getattr(record, "correlation_id", None),
            "result": getattr(record, "result", None),
            "duration_ms": getattr(record, "duration_ms", None),
            "message": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if fields is not None:
            payload["fields"] = redact_event(dict(fields))
        clean = {k: v for k, v in payload.items() if v is not None}
        return json.dumps(clean, ensure_ascii=False)


def log_event(
    logger: logging.Logger,
    *,
    event_name: str,
    event_code: str,
    component: str,
    correlation_id: str | None = None,
    result: str | None = None,
    duration_ms: int | None = None,
    fields: dict[str, Any] | None = None,
    level: int = logging.INFO,
) -> None:
    logger.log(
        level,
        event_name,
        extra={
            "event_name": event_name,
            "event_code": event_code,
            "component": component,
            "correlation_id": correlation_id,
            "result": result,
            "duration_ms": duration_ms,
            "fields": fields or {},
        },
    )


class StructuredLogger:
    """Application logger emitting JSON lines to stderr."""

    def __init__(self, component: str) -> None:
        self.component = component
        self._logger = logging.getLogger(f"tld.{component}")
        if not self._logger.handlers:
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(StructuredJsonFormatter())
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.INFO)
            self._logger.propagate = False

    def emit(
        self,
        *,
        level: str = "info",
        event_code: str,
        event_name: str | None = None,
        correlation_id: str | None = None,
        result: str | None = None,
        duration_ms: int | None = None,
        fields: dict[str, Any] | None = None,
    ) -> None:
        log_level = {
            "debug": logging.DEBUG,
            "info": logging.INFO,
            "warning": logging.WARNING,
            "error": logging.ERROR,
            "critical": logging.CRITICAL,
        }.get(level, logging.INFO)
        log_event(
            self._logger,
            event_name=event_name or event_code,
            event_code=event_code,
            component=self.component,
            correlation_id=correlation_id,
            result=result,
            duration_ms=duration_ms,
            fields=fields,
            level=log_level,
        )


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
