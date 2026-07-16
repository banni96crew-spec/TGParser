"""Retention purge — exports/tmp age and terminal outbox cleanup."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from telegram_lead_discovery.infrastructure.maintenance import run_daily_purge
from telegram_lead_discovery.infrastructure.paths import ensure_app_directories, resolve_app_paths
from telegram_lead_discovery.settings.service import seed_defaults
from telegram_lead_discovery.storage.db import dispose_engine, init_engine
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import NotificationDelivery, NotificationOutbox
from telegram_lead_discovery.storage.retention import purge_exports_and_tmp
from telegram_lead_discovery.storage.session import configure_session_factory, run_write


@pytest.fixture
async def purge_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    paths = ensure_app_directories(resolve_app_paths())
    upgrade_head(paths.database_path)
    engine = await init_engine(paths.database_path)
    configure_session_factory(engine)

    async def _seed(session):
        await seed_defaults(session)

    await run_write(_seed)
    yield paths
    await dispose_engine()


@pytest.mark.asyncio
async def test_purge_deletes_old_export_files(purge_env) -> None:
    paths = purge_env
    stale = paths.exports_dir / "stale.csv"
    stale.write_text("a,b\n", encoding="utf-8")
    old = time.time() - 7200
    os.utime(stale, (old, old))
    fresh = paths.tmp_dir / "fresh.tmp"
    fresh.write_text("ok", encoding="utf-8")

    deleted = purge_exports_and_tmp(paths, now=datetime.now(UTC))
    assert deleted >= 1
    assert not stale.exists()
    assert fresh.exists()


@pytest.mark.asyncio
async def test_daily_purge_removes_terminal_outbox(purge_env) -> None:
    paths = purge_env
    old = datetime.now(UTC) - timedelta(days=40)

    async def _seed(session):
        row = NotificationOutbox(
            event_type="hot_lead",
            lead_id=None,
            incident_id="inc-1",
            score_version=None,
            idempotency_key="hot_lead:old:1",
            state="sent",
            created_at=old,
        )
        session.add(row)
        await session.flush()
        session.add(
            NotificationDelivery(
                outbox_id=row.id,
                attempt_no=1,
                status="sent",
                attempted_at=old,
            )
        )
        return row.id

    await run_write(_seed)

    async def _purge(session):
        return await run_daily_purge(session, paths=paths, now=datetime.now(UTC))

    result = await run_write(_purge)
    assert result.terminal_outbox_deleted >= 1
