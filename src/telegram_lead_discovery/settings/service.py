"""Operator settings service (SET-003..SET-006, D-047)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.settings.defaults import (
    DEFAULT_SETTINGS,
    DEFAULTS,
    RECONCILIATION_INTERVAL_MAX,
    RECONCILIATION_INTERVAL_MIN,
    SETTING_GROUPS,
    SETTINGS_VERSION_KEY,
)
from telegram_lead_discovery.storage.models import OperatorSetting, SettingChange


class SettingsVersionConflict(Exception):
    pass


class SettingsValidationError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class SettingsSnapshot:
    settings_version: int
    values: dict[str, Any]


async def seed_defaults(session: AsyncSession) -> None:
    for key, (value_type, value) in DEFAULT_SETTINGS.items():
        existing = await session.get(OperatorSetting, key)
        if existing is None:
            session.add(
                OperatorSetting(
                    key=key,
                    value_json=json.dumps(value, ensure_ascii=False),
                    value_type=value_type,
                    version=1,
                )
            )
            session.add(
                SettingChange(
                    setting_key=key,
                    old_value_json=None,
                    new_value_json=json.dumps(value, ensure_ascii=False),
                    reason="startup_seed",
                    change_source="startup_seed",
                )
            )
    version_row = await session.get(OperatorSetting, SETTINGS_VERSION_KEY)
    if version_row is None:
        session.add(
            OperatorSetting(
                key=SETTINGS_VERSION_KEY,
                value_json=json.dumps(1),
                value_type="integer",
                version=1,
            )
        )
        session.add(
            SettingChange(
                setting_key=SETTINGS_VERSION_KEY,
                old_value_json=None,
                new_value_json=json.dumps(1),
                reason="startup_seed",
                change_source="startup_seed",
            )
        )
    await session.flush()


async def get_settings_version(session: AsyncSession) -> int:
    row = await session.get(OperatorSetting, SETTINGS_VERSION_KEY)
    if row is None:
        return 1
    return int(json.loads(row.value_json))


async def get_setting(session: AsyncSession, key: str) -> Any:
    row = await session.get(OperatorSetting, key)
    if row is None:
        if key in DEFAULT_SETTINGS:
            return DEFAULT_SETTINGS[key][1]
        # Compat aliases used by older foundation code / outbox
        if key == "notifications.delivery_mode":
            return "shadow"
        if key == "ui.timezone":
            return "Europe/Moscow"
        if key == "collector.periodic_reconciliation_minutes":
            return DEFAULT_SETTINGS["collector.reconciliation_interval_minutes"][1]
        raise KeyError(key)
    return json.loads(row.value_json)


async def get_snapshot(session: AsyncSession) -> SettingsSnapshot:
    result = await session.execute(select(OperatorSetting))
    values = {row.key: json.loads(row.value_json) for row in result.scalars()}
    for key, (_typ, default) in DEFAULT_SETTINGS.items():
        values.setdefault(key, default)
    values.pop(SETTINGS_VERSION_KEY, None)
    return SettingsSnapshot(
        settings_version=await get_settings_version(session),
        values=values,
    )


async def snapshot(session: AsyncSession) -> dict[str, Any]:
    snap = await get_snapshot(session)
    return {"settings_version": snap.settings_version, "values": snap.values}


def _validate(key: str, value: Any) -> None:
    if key == "notifications.delivery_mode" and value not in {"shadow", "live"}:
        raise SettingsValidationError("delivery_mode must be shadow|live")
    if key == "collector.reconciliation_interval_minutes":
        if (
            not isinstance(value, int)
            or value < RECONCILIATION_INTERVAL_MIN
            or value > RECONCILIATION_INTERVAL_MAX
        ):
            raise SettingsValidationError("invalid reconciliation interval")
    if key == "collector.periodic_reconciliation_minutes":
        if not isinstance(value, int) or value < 1 or value > 1440:
            raise SettingsValidationError("invalid reconciliation interval")


async def update_setting(
    session: AsyncSession,
    *,
    key: str,
    expected_settings_version: int,
    value: Any | None = None,
    typed_value: Any | None = None,
    source: str = "ui",
    change_source: str | None = None,
    reason: str | None = None,
) -> SettingsSnapshot:
    resolved_value = typed_value if typed_value is not None else value
    if resolved_value is None:
        raise SettingsValidationError("value required")
    current_version = await get_settings_version(session)
    if expected_settings_version != current_version:
        raise SettingsVersionConflict("settings_version_conflict")
    _validate(key, resolved_value)
    row = await session.get(OperatorSetting, key)
    old = None if row is None else row.value_json
    meta = DEFAULT_SETTINGS.get(key, ("string", None))
    value_type = meta[0] if key in DEFAULT_SETTINGS else type(resolved_value).__name__
    if row is None:
        row = OperatorSetting(
            key=key,
            value_json=json.dumps(resolved_value, ensure_ascii=False),
            value_type=value_type,
            version=1,
        )
        session.add(row)
    else:
        row.value_json = json.dumps(resolved_value, ensure_ascii=False)
        row.version += 1
        row.updated_at = datetime.now(UTC)
    session.add(
        SettingChange(
            setting_key=key,
            old_value_json=old,
            new_value_json=json.dumps(resolved_value, ensure_ascii=False),
            reason=reason,
            change_source=change_source or source,
        )
    )
    version_row = await session.get(OperatorSetting, SETTINGS_VERSION_KEY)
    if version_row is None:
        session.add(
            OperatorSetting(
                key=SETTINGS_VERSION_KEY,
                value_json=json.dumps(current_version + 1),
                value_type="integer",
                version=1,
            )
        )
    else:
        version_row.value_json = json.dumps(current_version + 1)
        version_row.updated_at = datetime.now(UTC)
    await session.flush()
    return await get_snapshot(session)


async def reset_setting(
    session: AsyncSession,
    *,
    key: str,
    expected_settings_version: int,
) -> SettingsSnapshot:
    if key not in DEFAULT_SETTINGS or key == SETTINGS_VERSION_KEY:
        raise SettingsValidationError("reset not allowed")
    return await update_setting(
        session,
        key=key,
        typed_value=DEFAULT_SETTINGS[key][1],
        expected_settings_version=expected_settings_version,
        change_source="system",
        reason="reset_to_default",
    )


# Re-exports for tests and callers
__all__ = [
    "DEFAULTS",
    "SETTING_GROUPS",
    "SettingsSnapshot",
    "SettingsValidationError",
    "SettingsVersionConflict",
    "get_setting",
    "get_settings_version",
    "get_snapshot",
    "reset_setting",
    "seed_defaults",
    "snapshot",
    "update_setting",
]
