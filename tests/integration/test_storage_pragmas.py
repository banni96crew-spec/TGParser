"""Integration — SQLite pragmas (STO-001)."""

from __future__ import annotations

from pathlib import Path

import pytest

from telegram_lead_discovery.infrastructure.paths import ensure_app_directories, resolve_app_paths
from telegram_lead_discovery.storage.db import (
    dispose_engine,
    get_engine,
    init_engine,
    probe_pragmas,
)
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.session import configure_session_factory


@pytest.fixture
async def db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    paths = ensure_app_directories(resolve_app_paths())
    upgrade_head(paths.database_path)
    engine = await init_engine(paths.database_path)
    configure_session_factory(engine)
    yield paths
    await dispose_engine()


@pytest.mark.asyncio
async def test_storage_pragmas(db_env) -> None:
    pragmas = await probe_pragmas(get_engine())
    assert pragmas["foreign_keys"] == 1
    assert pragmas["journal_mode"] == "WAL"
    assert pragmas["busy_timeout"] == 5000
