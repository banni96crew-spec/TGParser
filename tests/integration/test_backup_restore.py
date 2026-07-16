"""Unit/integration — backup integrity and restore guards."""

from __future__ import annotations

from pathlib import Path

import pytest

from telegram_lead_discovery.infrastructure.backup import (
    create_online_backup,
    restore_backup,
    rotate_backups,
)
from telegram_lead_discovery.infrastructure.paths import ensure_app_directories, resolve_app_paths
from telegram_lead_discovery.settings.service import seed_defaults
from telegram_lead_discovery.storage.db import dispose_engine, init_engine
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.session import configure_session_factory, run_write


@pytest.fixture
async def paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    resolved = ensure_app_directories(resolve_app_paths())
    upgrade_head(resolved.database_path)
    engine = await init_engine(resolved.database_path)
    configure_session_factory(engine)

    async def _seed(session):
        await seed_defaults(session)

    await run_write(_seed)
    yield resolved
    await dispose_engine()


@pytest.mark.asyncio
async def test_backup_and_restore(paths) -> None:
    async def _backup(session):
        return await create_online_backup(session, paths=paths, backup_type="daily")

    manifest = await run_write(_backup)
    backup_file = Path(manifest.path_ref)
    assert backup_file.exists()
    assert manifest.integrity_result == "ok"

    restored = restore_backup(backup_path=backup_file, paths=paths, runtime_running=False)
    assert restored.exists()

    with pytest.raises(RuntimeError, match="restore_requires_stopped_runtime"):
        restore_backup(backup_path=backup_file, paths=paths, runtime_running=True)


@pytest.mark.asyncio
async def test_backup_rotation(paths) -> None:
    for _ in range(9):

        async def _backup(session):
            return await create_online_backup(session, paths=paths, backup_type="daily")

        await run_write(_backup)
    removed = rotate_backups(paths, keep_daily=7, keep_weekly=4)
    assert removed >= 1
    assert len(list(paths.backups_dir.glob("daily-*.sqlite3"))) <= 7


@pytest.mark.asyncio
async def test_backup_weekly_rotation(paths) -> None:
    for _ in range(6):

        async def _weekly(session):
            return await create_online_backup(session, paths=paths, backup_type="weekly")

        await run_write(_weekly)
    removed = rotate_backups(paths, keep_daily=7, keep_weekly=4)
    assert removed >= 2
    assert len(list(paths.backups_dir.glob("weekly-*.sqlite3"))) <= 4
    assert len(list(paths.backups_dir.glob("weekly-*.sqlite3"))) == 4
