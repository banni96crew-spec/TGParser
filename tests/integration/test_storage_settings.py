"""Integration — SQLite pragmas, migrations, settings, secrets canary."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import select

from telegram_lead_discovery.infrastructure.paths import database_path, ensure_directories
from telegram_lead_discovery.security.secrets import read_secret_presence
from telegram_lead_discovery.settings.defaults import DEFAULT_SETTINGS, SETTING_GROUPS
from telegram_lead_discovery.settings.service import (
    SettingsValidationError,
    seed_defaults,
    snapshot,
    update_setting,
)
from telegram_lead_discovery.storage.db import (
    dispose_engine,
    init_engine,
    pragma_probe,
    session_scope,
)
from telegram_lead_discovery.storage.migrate import current_revision, upgrade_head
from telegram_lead_discovery.storage.models import SettingChange
from telegram_lead_discovery.storage.outbox import enqueue_hot_lead


@pytest.fixture
async def db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    ensure_directories()
    db_path = database_path()
    upgrade_head(db_path)
    await init_engine(db_path)
    yield db_path
    await dispose_engine()


@pytest.mark.asyncio
async def test_at_sto_001_pragmas(db_env) -> None:
    pragmas = await pragma_probe()
    assert int(pragmas["foreign_keys"]) == 1
    assert str(pragmas["journal_mode"]).upper() == "WAL"
    assert int(pragmas["busy_timeout"]) == 5000


@pytest.mark.asyncio
async def test_at_sto_003_migration_head(db_env) -> None:
    rev = current_revision(db_env)
    assert rev == "001_initial"


@pytest.mark.asyncio
async def test_at_set_003_004_005_settings(db_env) -> None:
    async with session_scope() as session:
        await seed_defaults(session)
        snap = await snapshot(session)
    assert snap["settings_version"] == 1
    assert snap["values"]["notifications.delivery_mode"] == "shadow"

    async with session_scope() as session:
        with pytest.raises(SettingsValidationError):
            await update_setting(
                session,
                key="collector.reconciliation_interval_minutes",
                value=2,
                expected_settings_version=1,
            )
        after_bad = await snapshot(session)
    assert after_bad["settings_version"] == 1
    assert after_bad["values"]["collector.reconciliation_interval_minutes"] == 30

    async with session_scope() as session:
        after_ok = await update_setting(
            session,
            key="collector.reconciliation_interval_minutes",
            value=60,
            expected_settings_version=1,
            source="ui",
        )
    # update_setting returns SettingsSnapshot dataclass
    assert after_ok.settings_version == 2
    assert after_ok.values["collector.reconciliation_interval_minutes"] == 60

    async with session_scope() as session:
        result = await session.execute(
            select(SettingChange).where(
                SettingChange.setting_key == "collector.reconciliation_interval_minutes",
                SettingChange.change_source == "ui",
            )
        )
        changes = list(result.scalars().all())
    assert len(changes) == 1


@pytest.mark.asyncio
async def test_at_set_001_groups_and_shadow_default(db_env) -> None:
    async with session_scope() as session:
        await seed_defaults(session)
        snap = await snapshot(session)
    groups = {k.split(".", 1)[0] for k in snap["values"] if "." in k}
    for required in SETTING_GROUPS:
        assert required in groups
    assert DEFAULT_SETTINGS["notifications.delivery_mode"][1] == "shadow"


@pytest.mark.asyncio
async def test_at_sec_004_secrets_not_in_sqlite(
    db_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    canary = "CANARY_BOT_TOKEN_VALUE_9f3a"
    monkeypatch.setenv("TG_BOT_TOKEN", canary)
    monkeypatch.setenv("TG_NOTIFY_CHAT_ID", "-100123")
    presence = read_secret_presence()
    assert presence.tg_bot_token is True

    async with session_scope() as session:
        await seed_defaults(session)
        result = await enqueue_hot_lead(session, lead_id=1, score_version=1)
        assert result is None

    raw = sqlite3.connect(db_env)
    try:
        dump = "\n".join(raw.iterdump())
    finally:
        raw.close()
    assert canary not in dump


@pytest.mark.asyncio
async def test_d047_shadow_skips_hot_lead(db_env) -> None:
    async with session_scope() as session:
        await seed_defaults(session)
        result = await enqueue_hot_lead(session, lead_id=1, score_version=1)
    assert result is None
