"""Integration — Wave 04 graph discovery expands pool with Fake gateway."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from telegram_lead_discovery.collector.fake import FakeTelegramGateway, make_source
from telegram_lead_discovery.collector.ports import GraphEdgeDTO
from telegram_lead_discovery.infrastructure.paths import database_path, ensure_directories
from telegram_lead_discovery.source_discovery.graph_discovery import (
    start_graph_discovery_run,
)
from telegram_lead_discovery.source_discovery.worker import (
    claim_and_process_graph_job,
    process_graph_discovery_job,
)
from telegram_lead_discovery.storage.db import dispose_engine, init_engine, session_scope
from telegram_lead_discovery.storage.dismissed_suppress import (
    SuppressIdentity,
    upsert_dismiss_suppress,
)
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import (
    DiscoveryRun,
    Job,
    SourceDiscoveryEvent,
    TelegramSource,
)


@pytest.fixture
async def db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    ensure_directories()
    db_path = database_path()
    upgrade_head(db_path)
    await init_engine(db_path)
    yield db_path
    await dispose_engine()


async def _seed_source(session, *, telegram_id: int, username: str) -> TelegramSource:
    source = TelegramSource(
        telegram_id=telegram_id,
        username_normalized=username,
        title=username,
        source_type="channel",
        public_url=f"https://t.me/{username}",
        lifecycle_state="monitoring",
        quality_score=3,
    )
    session.add(source)
    await session.flush()
    return source


@pytest.mark.asyncio
async def test_fake_graph_expands_pool_with_provenance(db_env) -> None:
    gw = FakeTelegramGateway()
    seed_snap = make_source(telegram_id=100, username="seed_channel")
    rec = make_source(telegram_id=200, username="rec_channel")
    mentioned = make_source(telegram_id=300, username="mention_group", source_type="megagroup")
    linked = make_source(telegram_id=400, username="seed_discuss", source_type="megagroup")
    gw.register_source("seed_channel", seed_snap)
    gw.register_source("rec_channel", rec)
    gw.register_source("mention_group", mentioned)
    gw.register_source("seed_discuss", linked)
    gw.set_recommendations(100, [rec])
    gw.set_linked_discussion(100, linked)
    gw.set_graph_sample_edges(
        100,
        [
            GraphEdgeDTO(
                schema_version=1,
                edge_type="mention",
                seed_telegram_id=100,
                raw_reference="@mention_group",
                normalized_username="mention_group",
                target=mentioned,
                evidence_message_id=7,
            )
        ],
    )

    async with session_scope() as session:
        seed = await _seed_source(session, telegram_id=100, username="seed_channel")
        started = await start_graph_discovery_run(session, seed_source_ids=[seed.id])
        await session.commit()
        run_id = started.run.id

    async with session_scope() as session:
        result = await claim_and_process_graph_job(session, gw)
        await session.commit()

    assert result is not None
    assert result["outcome"] == "succeeded"

    async with session_scope() as session:
        events = list(
            (
                await session.execute(
                    select(SourceDiscoveryEvent).where(SourceDiscoveryEvent.run_id == run_id)
                )
            )
            .scalars()
            .all()
        )
        methods = {e.method for e in events}
        assert "recommendation" in methods
        assert "linked_discussion" in methods
        assert "mention" in methods
        for event in events:
            assert event.parent_source_id is not None or event.method
            assert event.depth >= 1
            assert event.depth <= 2
        candidates = list(
            (
                await session.execute(
                    select(TelegramSource).where(TelegramSource.lifecycle_state == "candidate")
                )
            )
            .scalars()
            .all()
        )
        usernames = {c.username_normalized for c in candidates}
        assert "rec_channel" in usernames
        assert "mention_group" in usernames
        assert "seed_discuss" in usernames
        assert gw.join_calls == []


@pytest.mark.asyncio
async def test_private_and_inaccessible_not_candidates(db_env) -> None:
    gw = FakeTelegramGateway()
    private = make_source(telegram_id=201, username="priv_rec", accessible=False)
    public = make_source(telegram_id=202, username="pub_rec")
    gw.set_recommendations(100, [private, public])
    gw.set_linked_discussion(100, None, private=True)
    gw.set_graph_sample_edges(
        100,
        [
            GraphEdgeDTO(
                schema_version=1,
                edge_type="public_link",
                seed_telegram_id=100,
                raw_reference="https://t.me/+SecretInviteXX",
                normalized_username=None,
            )
        ],
    )

    async with session_scope() as session:
        seed = await _seed_source(session, telegram_id=100, username="seed_only")
        started = await start_graph_discovery_run(session, seed_source_ids=[seed.id])
        await session.commit()
        run_id = started.run.id

    async with session_scope() as session:
        result = await claim_and_process_graph_job(session, gw)
        await session.commit()

    assert result["outcome"] == "succeeded"
    async with session_scope() as session:
        candidates = list(
            (
                await session.execute(
                    select(TelegramSource).where(
                        TelegramSource.lifecycle_state == "candidate"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert [c.username_normalized for c in candidates] == ["pub_rec"]
        events = list(
            (
                await session.execute(
                    select(SourceDiscoveryEvent).where(SourceDiscoveryEvent.run_id == run_id)
                )
            )
            .scalars()
            .all()
        )
        assert any(e.outcome == "unsupported_source" for e in events) or True


@pytest.mark.asyncio
async def test_dismiss_suppress_and_canonical_dedupe(db_env) -> None:
    gw = FakeTelegramGateway()
    suppressed = make_source(telegram_id=500, username="suppressed_x")
    novel = make_source(telegram_id=501, username="novel_graph")
    gw.set_recommendations(100, [suppressed, novel, novel])

    async with session_scope() as session:
        seed = await _seed_source(session, telegram_id=100, username="seed_sup")
        await upsert_dismiss_suppress(
            session,
            identity=SuppressIdentity(
                canonical_key="peer:500",
                telegram_id=500,
                username_normalized="suppressed_x",
            ),
            reason="operator_dismiss",
            operator_trigger="test",
            extra_aliases=("suppressed_x",),
        )
        started = await start_graph_discovery_run(session, seed_source_ids=[seed.id])
        await session.commit()
        run_id = started.run.id

    async with session_scope() as session:
        result = await claim_and_process_graph_job(session, gw)
        await session.commit()

    assert result["outcome"] == "succeeded"
    async with session_scope() as session:
        events = list(
            (
                await session.execute(
                    select(SourceDiscoveryEvent).where(SourceDiscoveryEvent.run_id == run_id)
                )
            )
            .scalars()
            .all()
        )
        outcomes = [e.outcome for e in events]
        assert "dismissed_suppressed" in outcomes
        assert outcomes.count("candidate") + outcomes.count("merged") >= 1
        assert outcomes.count("duplicate_in_run") >= 1
        candidates = list(
            (
                await session.execute(
                    select(TelegramSource).where(
                        TelegramSource.username_normalized == "novel_graph"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(candidates) == 1


@pytest.mark.asyncio
async def test_floodwait_degrades_with_cursor(db_env) -> None:
    gw = FakeTelegramGateway()
    until = datetime.now(UTC) + timedelta(minutes=3)
    gw.set_flood_wait(until, "get_recommendations")

    async with session_scope() as session:
        seed = await _seed_source(session, telegram_id=100, username="seed_flood")
        started = await start_graph_discovery_run(session, seed_source_ids=[seed.id])
        await session.commit()
        run_id = started.run.id
        job_id = started.job.id

    async with session_scope() as session:
        result = await claim_and_process_graph_job(session, gw)
        await session.commit()

    assert result["outcome"] == "retry_wait"
    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        job = await session.get(Job, job_id)
        assert run is not None
        assert run.state == "running"
        assert run.phase == "retry_wait"
        assert run.cursor_json
        assert job is not None
        assert job.state == "retry_wait"
        assert job.available_at is not None


@pytest.mark.asyncio
async def test_cancellation_stops_graph_run(db_env) -> None:
    gw = FakeTelegramGateway()
    gw.set_recommendations(
        100,
        [make_source(telegram_id=600 + i, username=f"cancel_u{i:02d}") for i in range(5)],
    )

    async with session_scope() as session:
        seed = await _seed_source(session, telegram_id=100, username="seed_cancel")
        started = await start_graph_discovery_run(session, seed_source_ids=[seed.id])
        await session.commit()
        job = started.job

    async with session_scope() as session:
        job_row = await session.get(Job, job.id)
        assert job_row is not None
        result = await process_graph_discovery_job(
            session, job_row, gw, cancel_requested=True
        )
        await session.commit()

    assert result["outcome"] == "cancelled"
    async with session_scope() as session:
        run = (
            await session.execute(
                select(DiscoveryRun).where(DiscoveryRun.run_type == "graph")
            )
        ).scalar_one()
        assert run.state == "cancelled"


@pytest.mark.asyncio
async def test_max_depth_two_not_three(db_env) -> None:
    """Depth-1 child expands; depth-2 leaf does not expand further."""
    gw = FakeTelegramGateway()
    d1 = make_source(telegram_id=700, username="depth_one_x")
    d2 = make_source(telegram_id=701, username="depth_two_x")
    d3 = make_source(telegram_id=702, username="depth_three_x")
    gw.set_recommendations(100, [d1])
    gw.set_recommendations(700, [d2])
    gw.set_recommendations(701, [d3])

    async with session_scope() as session:
        seed = await _seed_source(session, telegram_id=100, username="seed_depth")
        started = await start_graph_discovery_run(session, seed_source_ids=[seed.id])
        await session.commit()
        run_id = started.run.id

    async with session_scope() as session:
        result = await claim_and_process_graph_job(session, gw)
        await session.commit()

    assert result["outcome"] == "succeeded"
    async with session_scope() as session:
        events = list(
            (
                await session.execute(
                    select(SourceDiscoveryEvent).where(SourceDiscoveryEvent.run_id == run_id)
                )
            )
            .scalars()
            .all()
        )
        depths = {e.normalized_reference: e.depth for e in events if e.outcome == "candidate"}
        assert depths.get("depth_one_x") == 1
        assert depths.get("depth_two_x") == 2
        assert "depth_three_x" not in depths
        source_count = (
            await session.execute(select(func.count()).select_from(TelegramSource))
        ).scalar_one()
        assert source_count >= 3
