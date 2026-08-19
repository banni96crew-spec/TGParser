from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from telegram_lead_discovery.infrastructure.paths import database_path, ensure_directories
from telegram_lead_discovery.source_discovery.graph_discovery import (
    GraphRunStartError,
    start_graph_discovery_run,
)
from telegram_lead_discovery.source_discovery.keyword_run import (
    KeywordRunStartError,
    start_keyword_discovery_run,
)
from telegram_lead_discovery.storage.db import (
    dispose_engine,
    init_engine,
    session_scope,
)
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import DiscoveryRun, TelegramSource


@pytest.fixture
async def db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    ensure_directories()
    path = database_path()
    upgrade_head(path)
    await init_engine(path)
    yield path
    await dispose_engine()


async def _seed(session) -> TelegramSource:
    source = TelegramSource(
        telegram_id=101,
        access_hash=202,
        username_normalized="seed_mutex",
        title="seed",
        source_type="channel",
        lifecycle_state="monitoring",
        quality_score=3,
    )
    session.add(source)
    await session.flush()
    return source


@pytest.mark.asyncio
async def test_keyword_start_rejected_while_graph_is_active(db_env) -> None:
    async with session_scope() as session:
        seed = await _seed(session)
        started = await start_graph_discovery_run(session, seed_source_ids=[seed.id])
        await session.commit()
        with pytest.raises(
            KeywordRunStartError,
            match=rf"telegram_discovery_busy:graph:{started.run.id}",
        ):
            await start_keyword_discovery_run(session, profile_id=999)


@pytest.mark.asyncio
async def test_graph_start_rejected_while_keyword_is_active(db_env) -> None:
    async with session_scope() as session:
        seed = await _seed(session)
        keyword = DiscoveryRun(
            run_type="keyword_scouting",
            state="running",
            max_depth=2,
            expansion_cap=25,
            candidate_cap=100,
            counters_json="{}",
        )
        session.add(keyword)
        await session.flush()
        with pytest.raises(
            GraphRunStartError,
            match=rf"telegram_discovery_busy:keyword_scouting:{keyword.id}",
        ):
            await start_graph_discovery_run(session, seed_source_ids=[seed.id])


@pytest.mark.asyncio
async def test_terminal_run_releases_unique_active_slot(db_env) -> None:
    async with session_scope() as session:
        seed = await _seed(session)
        old = DiscoveryRun(
            run_type="keyword_scouting",
            state="failed",
            max_depth=2,
            expansion_cap=25,
            candidate_cap=100,
            counters_json="{}",
        )
        session.add(old)
        await session.flush()
        started = await start_graph_discovery_run(session, seed_source_ids=[seed.id])
        assert started.run.state == "queued"


@pytest.mark.asyncio
async def test_database_index_rejects_two_active_modes(db_env) -> None:
    async with session_scope() as session:
        session.add(
            DiscoveryRun(
                run_type="graph",
                state="running",
                max_depth=2,
                expansion_cap=25,
                candidate_cap=100,
                counters_json="{}",
            )
        )
        await session.flush()
        session.add(
            DiscoveryRun(
                run_type="keyword_scouting",
                state="queued",
                max_depth=2,
                expansion_cap=25,
                candidate_cap=100,
                counters_json="{}",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()
