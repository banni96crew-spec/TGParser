"""AT-STO-025 — in-flight graph discovery jobs are not requeued."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from telegram_lead_discovery.infrastructure.paths import database_path, ensure_directories
from telegram_lead_discovery.storage.db import dispose_engine, init_engine, session_scope
from telegram_lead_discovery.storage.jobs import (
    drop_inflight_discovery_job,
    mark_inflight_discovery_job,
    recover_stale_jobs,
)
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import Job


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
async def test_inflight_discovery_job_skips_stale_reclaim(db_env) -> None:
    now = datetime.now(UTC)
    async with session_scope() as session:
        job = Job(
            job_type="discovery",
            dedupe_key="graph-discovery:sto025",
            state="running",
            payload_json="{}",
            lease_until=now - timedelta(seconds=10),
            updated_at=now,
            created_at=now,
        )
        session.add(job)
        await session.flush()
        job_id = job.id
        mark_inflight_discovery_job(job_id)
        await session.commit()
    try:
        async with session_scope() as session:
            recovered = await recover_stale_jobs(session)
            job = await session.get(Job, job_id)
            assert recovered == 0
            assert job.state == "running"
            await session.commit()
        drop_inflight_discovery_job(job_id)
        async with session_scope() as session:
            recovered = await recover_stale_jobs(session)
            job = await session.get(Job, job_id)
            assert recovered == 1
            assert job.state == "queued"
            await session.commit()
    finally:
        drop_inflight_discovery_job(job_id)
