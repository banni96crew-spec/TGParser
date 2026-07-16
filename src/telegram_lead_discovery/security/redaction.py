from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

_SENSITIVE_KEYS = frozenset(
    {
        "api_hash",
        "tg_api_hash",
        "bot_token",
        "tg_bot_token",
        "authorization",
        "session",
        "password",
        "token",
        "secret",
    }
)

_URI_CREDENTIALS = re.compile(r"(://[^:/@\s]+:)([^@/\s]+)(@)")
_BEARER = re.compile(r"(Bearer\s+)\S+", re.IGNORECASE)
_LONG_TOKEN = re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{20,}\b")


def redact_text(value: str) -> str:
    text = _URI_CREDENTIALS.sub(rf"\1{REDACTED}\3", value)
    text = _BEARER.sub(rf"\1{REDACTED}", text)
    return _LONG_TOKEN.sub(REDACTED, text)


def redact_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    return {
        key: (
            REDACTED
            if str(key).lower() in _SENSITIVE_KEYS
            else redact_value(item)
        )
        for key, item in mapping.items()
    }


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return redact_mapping(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_event(fields: dict[str, Any]) -> dict[str, Any]:
    return redact_mapping(fields)
