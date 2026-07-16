"""Integration — approve source → initial_backfill via fake gateway."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from telegram_lead_discovery.collector.fake import FakeTelegramGateway
from telegram_lead_discovery.collector.ports import SourceSnapshot, TelegramMessageDTO
from telegram_lead_discovery.collector.service import handle_backfill_job
from telegram_lead_discovery.infrastructure.paths import ensure_app_directories, resolve_app_paths
from telegram_lead_discovery.settings.service import seed_defaults
from telegram_lead_discovery.source_discovery.service import (
    add_manual_candidate,
    approve_source,
    normalize_username,
)
from telegram_lead_discovery.storage.db import dispose_engine, init_engine
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import Job, TelegramEventEnvelope, TelegramSource
from telegram_lead_discovery.storage.session import configure_session_factory, run_write


@pytest.fixture
async def db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    paths = ensure_app_directories(resolve_app_paths())
    upgrade_head(paths.database_path)
    engine = await init_engine(paths.database_path)
    configure_session_factory(engine)
    await run_write(seed_defaults)
    yield paths
    await dispose_engine()


def test_src_001_normalize_username() -> None:
    assert normalize_username("https://t.me/Test_Channel/?x=1") == "test_channel"


@pytest.mark.asyncio
async def test_approve_enqueues_backfill_and_persists(db_env) -> None:
    from datetime import UTC, datetime

    snap = SourceSnapshot(
        schema_version=1,
        telegram_id=1001,
        username="test_channel",
        title="Test Channel",
        source_type="channel",
        public_url="https://t.me/test_channel",
        accessible=True,
    )
    gateway = FakeTelegramGateway(sources={"test_channel": snap})
    now = datetime.now(UTC)
    gateway.register_messages(
        1,  # will be remapped after source insert — set after create
        [],
    )

    async def _add(session):
        source, _run = await add_manual_candidate(
            session, username_or_url="https://t.me/Test_Channel", gateway=gateway
        )
        return source.id

    source_id = await run_write(_add)

    gateway.register_messages(
        source_id,
        [
            TelegramMessageDTO(
                schema_version=1,
                source_id=source_id,
                telegram_message_id=10,
                published_at=now,
                text="Нужно разработать сайт, бюджет 150000 ₽.",
                permalink="https://t.me/test_channel/10",
            )
        ],
    )

    async def _approve(session):
        return await approve_source(session, source_id=source_id, gateway=gateway)

    source = await run_write(_approve)
    assert source.lifecycle_state == "monitoring"

    async def _job(session):
        result = await session.execute(
            select(Job).where(
                Job.job_type == "initial_backfill",
                Job.dedupe_key == f"initial_backfill:{source_id}",
            )
        )
        return result.scalar_one()

    job = await run_write(_job)
    assert job.state == "queued"

    async def _run_backfill(session):
        job_row = await session.get(Job, job.id)
        assert job_row is not None
        return await handle_backfill_job(session, job_row, gateway)

    outcome = await run_write(_run_backfill)
    assert outcome["outcome"] == "succeeded"
    assert outcome["persisted"] == 1

    async def _envelopes(session):
        result = await session.execute(select(TelegramEventEnvelope))
        return list(result.scalars().all())

    envelopes = await run_write(_envelopes)
    assert len(envelopes) == 1
    assert envelopes[0].processing_state == "queued"

    async def _source(session):
        return await session.get(TelegramSource, source_id)

    refreshed = await run_write(_source)
    assert refreshed is not None
    assert refreshed.lifecycle_state == "monitoring"
