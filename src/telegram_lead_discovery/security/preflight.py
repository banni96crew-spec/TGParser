from __future__ import annotations

from telegram_lead_discovery.security.bind_guard import assert_loopback_bind
from telegram_lead_discovery.security.secrets import read_secret_presence
from telegram_lead_discovery.security.types import SecurityPreflightResult


def run_security_preflight(*, bind: str = "127.0.0.1") -> SecurityPreflightResult:
    checks: list[str] = []
    fatal: list[str] = []

    try:
        assert_loopback_bind(bind)
        checks.append("bind_loopback")
    except ValueError as exc:
        fatal.append(str(exc))

    presence = read_secret_presence()
    if presence.telegram_ready:
        checks.append("telegram_credentials_present")
    else:
        fatal.append("telegram_credentials_missing")

    if presence.notifications_ready:
        checks.append("notifications_credentials_present")
    else:
        checks.append("notifications_optional_missing")

    return SecurityPreflightResult(
        status="passed" if not fatal else "blocked",
        checks=tuple(checks),
        safe_errors=tuple(fatal),
    )
