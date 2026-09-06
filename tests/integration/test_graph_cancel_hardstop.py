"""AT-SRC-057 — graph cancel interrupts wait and does not SRC-056-skip."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from telethon.client.users import UserMethods
from telethon.tl.types import InputPeerChannel

from telegram_lead_discovery.collector.adapter.controlled_client import (
    ControlledTelegramClient,
    _AsyncReadWriteLock,
)
from telegram_lead_discovery.collector.adapter.telethon_gateway import (
    TelethonTelegramGateway,
)
from telegram_lead_discovery.collector.fake import FakeTelegramGateway
from telegram_lead_discovery.infrastructure.paths import database_path, ensure_directories
from telegram_lead_discovery.source_discovery.graph_cancel import (
    cancel_graph_discovery_run,
    graph_cancel_event,
)
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
        access_hash=telegram_id + 1,
    )
    session.add(source)
    await session.flush()
    return source


def _client() -> ControlledTelegramClient:
    client = object.__new__(ControlledTelegramClient)
    client._request_access = _AsyncReadWriteLock()
    client._request_retries = 5
    client._flood_sleep_threshold = 60
    client._sender = object()
    client.session = _OfflineSession()
    return client


async def _wait_registered(run_id: int) -> None:
    for _ in range(50):
        if graph_cancel_event(run_id) is not None:
            return
        await asyncio.sleep(0.02)
    raise AssertionError("graph_cancel_event_not_registered")


class _OfflineSession:
    def get_input_entity(self, key):
        if isinstance(key, int):
            return InputPeerChannel(channel_id=key, access_hash=key + 1)
        raise ValueError("not_cached")


@pytest.mark.asyncio
async def test_cancel_during_eternal_rpc_is_cancelled_not_skip(
    db_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def hang(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(UserMethods, "_call", hang)
    gateway = TelethonTelegramGateway(client=_client())
    async with session_scope() as session:
        seed = await _seed(session, telegram_id=100, username="seed_hang")
        started = await start_graph_discovery_run(session, seed_source_ids=[seed.id])
        job_id = started.job.id
        run_id = started.run.id
        version = started.run.version
        await session.commit()

    async def worker() -> dict:
        async with session_scope() as session:
            job = await session.get(Job, job_id)
            result = await process_graph_discovery_job(session, job, gateway)
            await session.commit()
            return result

    task = asyncio.create_task(worker())
    await _wait_registered(run_id)
    await asyncio.sleep(0.2)
    async with session_scope() as session:
        cancelled = await cancel_graph_discovery_run(
            session, run_id=run_id, expected_version=version
        )
        assert cancelled.run.state == "cancelling"
    outcome = await asyncio.wait_for(task, timeout=1)
    assert outcome["outcome"] == "cancelled"
    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        assert run.state == "cancelled"
        counters = json.loads(run.counters_json or "{}")
        assert int(counters.get("node_timeout_total") or 0) == 0


@pytest.mark.asyncio
async def test_cancel_during_restart_cooldown_finishes(
    db_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = {"n": 0}

    async def track(*args, **kwargs):
        called["n"] += 1
        return type("Result", (), {"chats": []})()

    monkeypatch.setattr(UserMethods, "_call", track)
    gateway = TelethonTelegramGateway(client=_client())
    async with session_scope() as session:
        seed = await _seed(session, telegram_id=110, username="seed_cool")
        started = await start_graph_discovery_run(session, seed_source_ids=[seed.id])
        cursor = json.loads(started.run.cursor_json or "{}")
        cursor["request_control"] = {"reserved_total": 1}
        started.run.cursor_json = json.dumps(cursor)
        job_id = started.job.id
        run_id = started.run.id
        version = started.run.version
        await session.commit()

    async def worker() -> dict:
        async with session_scope() as session:
            job = await session.get(Job, job_id)
            return await process_graph_discovery_job(session, job, gateway)

    task = asyncio.create_task(worker())
    await _wait_registered(run_id)
    await asyncio.sleep(0.2)
    async with session_scope() as session:
        await cancel_graph_discovery_run(
            session, run_id=run_id, expected_version=version
        )
    outcome = await asyncio.wait_for(task, timeout=5)
    assert outcome["outcome"] == "cancelled"
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_cancel_retry_wait_is_immediate_without_telegram(db_env) -> None:
    gw = FakeTelegramGateway()
    async with session_scope() as session:
        seed = await _seed(session, telegram_id=120, username="seed_retry")
        started = await start_graph_discovery_run(session, seed_source_ids=[seed.id])
        started.job.state = "retry_wait"
        started.job.available_at = datetime.now(UTC) + timedelta(hours=1)
        started.run.state = "running"
        job_id = started.job.id
        run_id = started.run.id
        version = started.run.version
        await session.commit()
    async with session_scope() as session:
        result = await cancel_graph_discovery_run(
            session, run_id=run_id, expected_version=version
        )
        assert result.run.state == "cancelled"
    async with session_scope() as session:
        job = await session.get(Job, job_id)
        outcome = await process_graph_discovery_job(session, job, gw)
        await session.commit()
    assert outcome["outcome"] == "already_terminal"
    assert gw.get_recommendations_calls == []


@pytest.mark.asyncio
async def test_cancel_during_exclusive_wait_is_not_timeout(
    db_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*args, **kwargs):
        raise AssertionError("rpc_started")

    monkeypatch.setattr(UserMethods, "_call", boom)
    client = _client()
    gateway = TelethonTelegramGateway(client=client)
    hold = asyncio.Event()

    async def hold_shared() -> None:
        async with client._request_access.shared():
            await hold.wait()

    holder = asyncio.create_task(hold_shared())
    await asyncio.sleep(0)
    async with session_scope() as session:
        seed = await _seed(session, telegram_id=130, username="seed_lock")
        started = await start_graph_discovery_run(session, seed_source_ids=[seed.id])
        job_id = started.job.id
        run_id = started.run.id
        version = started.run.version
        await session.commit()

    async def worker() -> dict:
        async with session_scope() as session:
            job = await session.get(Job, job_id)
            return await process_graph_discovery_job(session, job, gateway)

    task = asyncio.create_task(worker())
    await _wait_registered(run_id)
    await asyncio.sleep(0.2)
    async with session_scope() as session:
        cancelled = await cancel_graph_discovery_run(
            session, run_id=run_id, expected_version=version
        )
        assert cancelled.run.state == "cancelling"
    try:
        outcome = await asyncio.wait_for(task, timeout=1)
        assert outcome["outcome"] == "cancelled"
    finally:
        hold.set()
        await holder
    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        assert run.state == "cancelled"
        counters = json.loads(run.counters_json or "{}")
        assert int(counters.get("node_timeout_total") or 0) == 0
