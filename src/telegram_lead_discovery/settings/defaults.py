"""Approved default operator settings (SET-006, D-047)."""

from __future__ import annotations

from typing import Any

SETTINGS_VERSION_KEY = "settings_version"

RECONCILIATION_INTERVAL_MIN = 5
RECONCILIATION_INTERVAL_MAX = 1440

SETTING_GROUPS = (
    "telegram",
    "discovery",
    "collector",
    "rules",
    "scoring",
    "notifications",
    "storage",
    "observability",
    "ui",
)

# key -> (value_type, default_value)
DEFAULT_SETTINGS: dict[str, tuple[str, Any]] = {
    "telegram.account_label": ("string", "primary"),
    "discovery.max_depth": ("integer", 2),
    "discovery.expansion_cap": ("integer", 25),
    "collector.reconciliation_interval_minutes": ("integer", 30),
    "collector.backfill_batch_size": ("integer", 100),
    "rules.active_profile": ("string", "default"),
    "scoring.hot_threshold": ("integer", 70),
    "notifications.delivery_mode": ("string", "shadow"),
    "storage.retention_lead_days": ("integer", 180),
    "observability.heartbeat_interval_seconds": ("integer", 30),
    "ui.timezone": ("string", "Europe/Moscow"),
    "ui.page_size": ("integer", 50),
}

# Back-compat aliases for older callers
DEFAULTS = {
    key: {"type": typ, "value": val} for key, (typ, val) in DEFAULT_SETTINGS.items()
}
DEFAULTS[SETTINGS_VERSION_KEY] = {"type": "integer", "value": 1}
