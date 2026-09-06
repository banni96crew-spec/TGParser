"""AT-SRC-056 — graph node timeout skip and one transient retry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from telegram_lead_discovery.collector.fake import FakeTelegramGateway, make_source
from telegram_lead_discovery.collector.ports import (
    GatewayPermanentError,
    GatewaySourceInaccessible,
    GatewayTimeout,
    GatewayTransientError,
)
from telegram_lead_discovery.infrastructure.paths import database_path, ensure_directories
from telegram_lead_discovery.source_discovery.graph_discovery import (
    start_graph_discovery_run,
)
from telegram_lead_discovery.source_discovery.worker import process_graph_discovery_job
from telegram_lead_discovery.storage.db import dispose_engine, init_engine, session_scope
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import DiscoveryRun, Job, TelegramSource


@pytest.fixture
async def db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    ensure_directories()
    db_path = database_path()
    upgrade_head(db_path)
    await init_engine(db_path)
    yield db_path
    await dispose_engine()


async def _seed(session, *, telegram_id: int, username: str) -> TelegramSource:
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


class _TimeoutFirstSeed(FakeTelegramGateway):
    async def get_recommendations(self, source, limit):
        if source.telegram_id == 101:
            raise GatewayTimeout()
        return await super().get_recommendations(source, limit)


class _TimeoutLinked(FakeTelegramGateway):
    async def get_linked_discussion(self, source):
        raise GatewayTimeout()


class _AlwaysTransient(FakeTelegramGateway):
    async def get_recommendations(self, source, limit):
        self.get_recommendations_calls.append((source, limit))
        raise GatewayTransientError("net")


@pytest.mark.asyncio
async def test_timeout_skips_first_seed_and_continues_bfs(db_env) -> None:
    gw = _TimeoutFirstSeed()
    gw.set_recommendations(102, [make_source(telegram_id=202, username="second_ok")])
    async with session_scope() as session:
        first = await _seed(session, telegram_id=101, username="seed_timeout")
        second = await _seed(session, telegram_id=102, username="seed_ok")
        started = await start_graph_discovery_run(
            session, seed_source_ids=[first.id, second.id]
        )
        job_id = started.job.id
        run_id = started.run.id
        await session.commit()
    async with session_scope() as session:
        job = await session.get(Job, job_id)
        result = await process_graph_discovery_job(session, job, gw)
        await session.commit()
    assert result["outcome"] == "succeeded"
    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        cursor = json.loads(run.cursor_json)
        assert set(cursor["completed_stages"]["peer:101"]) == {
            "resolve",
            "recommendations",
            "linked_discussion",
            "message_sample_100",
        }
        assert cursor["stage_results"]["peer:101"]["recommendations"] == []
        assert json.loads(run.counters_json)["node_timeout_total"] >= 1
        rec_before = len(gw.get_recommendations_calls)
        run.state = "queued"
        run.finished_at = None
        run.phase = "expand"
        job = await session.get(Job, job_id)
        job.state = "queued"
        job.lease_until = None
        await session.commit()
    async with session_scope() as session:
        job = await session.get(Job, job_id)
        result = await process_graph_discovery_job(session, job, gw)
        await session.commit()
    assert result["outcome"] in {"succeeded", "already_terminal"}
    assert len(gw.get_recommendations_calls) == rec_before


@pytest.mark.asyncio
async def test_saved_recommendations_are_kept_without_resolving(
    db_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from telegram_lead_discovery.source_discovery import graph_candidate_resolution

    resolves = {"n": 0}
    original = graph_candidate_resolution.resolve_planned_candidate

    async def counted(*args, **kwargs):
        resolves["n"] += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(
        "telegram_lead_discovery.source_discovery.worker_parts.graph_stages.resolve_planned_candidate",
        counted,
    )
    gw = _TimeoutLinked()
    rec = make_source(telegram_id=250, username="kept_rec")
    gw.set_recommendations(100, [rec])
    async with session_scope() as session:
        seed = await _seed(session, telegram_id=100, username="seed_saved")
        started = await start_graph_discovery_run(session, seed_source_ids=[seed.id])
        job_id = started.job.id
        run_id = started.run.id
        await session.commit()
    async with session_scope() as session:
        job = await session.get(Job, job_id)
        result = await process_graph_discovery_job(session, job, gw)
        await session.commit()
    assert result["outcome"] == "succeeded"
    assert resolves["n"] == 0
    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        cursor = json.loads(run.cursor_json)
        saved = cursor["stage_results"]["peer:100"]["recommendations"]
        assert saved
        assert saved[0]["normalized_username"] == "kept_rec"
        assert cursor["stage_results"]["peer:100"]["linked_discussion"] == []


@pytest.mark.asyncio
async def test_second_transient_skips_instead_of_parking(db_env) -> None:
    gw = _AlwaysTransient()
    async with session_scope() as session:
        seed = await _seed(session, telegram_id=100, username="seed_transient")
        started = await start_graph_discovery_run(session, seed_source_ids=[seed.id])
        job_id = started.job.id
        run_id = started.run.id
        await session.commit()
    async with session_scope() as session:
        job = await session.get(Job, job_id)
        first = await process_graph_discovery_job(session, job, gw)
        await session.commit()
    assert first["outcome"] == "retry_wait"
    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        cursor = json.loads(run.cursor_json)
        assert cursor["transient_counts"]["peer:100"] == 1
        job = await session.get(Job, job_id)
        job.available_at = None
        job.state = "queued"
        second = await process_graph_discovery_job(session, job, gw)
        await session.commit()
    assert second["outcome"] == "succeeded"
    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        assert run.state == "succeeded"
        assert json.loads(run.counters_json)["node_timeout_total"] >= 1
        assert run.last_error_code != "source_inaccessible"


class _PermanentFirstSeed(FakeTelegramGateway):
    async def get_recommendations(self, source, limit):
        if source.telegram_id == 101:
            raise GatewayPermanentError("USERNAME_NOT_OCCUPIED")
        return await super().get_recommendations(source, limit)


class _InaccessibleFirstSeed(FakeTelegramGateway):
    async def get_recommendations(self, source, limit):
        if source.telegram_id == 101:
            raise GatewaySourceInaccessible("USERNAME_NOT_OCCUPIED")
        return await super().get_recommendations(source, limit)


async def _two_seed_run(session):
    first = await _seed(session, telegram_id=101, username="seed_fail")
    second = await _seed(session, telegram_id=102, username="seed_ok")
    started = await start_graph_discovery_run(
        session, seed_source_ids=[first.id, second.id]
    )
    await session.commit()
    return started.job.id, started.run.id


@pytest.mark.asyncio
async def test_permanent_error_skips_node_and_continues_bfs(db_env) -> None:
    gw = _PermanentFirstSeed()
    gw.set_recommendations(102, [make_source(telegram_id=202, username="second_ok")])
    async with session_scope() as session:
        job_id, run_id = await _two_seed_run(session)
    async with session_scope() as session:
        job = await session.get(Job, job_id)
        result = await process_graph_discovery_job(session, job, gw)
        await session.commit()
    assert result["outcome"] == "succeeded"
    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        job = await session.get(Job, job_id)
        cursor = json.loads(run.cursor_json)
        assert job.state != "running"
        assert run.state == "succeeded"
        assert set(cursor["completed_stages"]["peer:101"]) == {
            "resolve",
            "recommendations",
            "linked_discussion",
            "message_sample_100",
        }
        assert json.loads(run.counters_json).get("node_timeout_total", 0) == 0


@pytest.mark.asyncio
async def test_inaccessible_skips_node_and_continues_bfs(db_env) -> None:
    gw = _InaccessibleFirstSeed()
    gw.set_recommendations(102, [make_source(telegram_id=202, username="second_ok")])
    async with session_scope() as session:
        job_id, run_id = await _two_seed_run(session)
    async with session_scope() as session:
        job = await session.get(Job, job_id)
        result = await process_graph_discovery_job(session, job, gw)
        await session.commit()
    assert result["outcome"] == "succeeded"
    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        job = await session.get(Job, job_id)
        assert job.state != "running"
        assert run.state == "succeeded"
