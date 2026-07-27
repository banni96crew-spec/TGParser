"""Wave 06 — runtime coordinator loops, failure isolation, restart (INF-022 / D-066)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from telegram_lead_discovery.collector.fake import FakeTelegramGateway, make_source
from telegram_lead_discovery.collector.service import enqueue_startup_reconciliation
from telegram_lead_discovery.infrastructure.paths import ensure_app_directories, resolve_app_paths
from telegram_lead_discovery.infrastructure.runtime import (
    PERIODIC_RECONCILE_SECONDS,
    RuntimeCoordinator,
    SupervisedLoop,
)
from telegram_lead_discovery.notifications.worker import NotificationOutboxLoop
from telegram_lead_discovery.observability.health import HealthState, reset_health_registry
from telegram_lead_discovery.settings.service import seed_defaults
from telegram_lead_discovery.source_discovery.service import add_manual_candidate, approve_source
from telegram_lead_discovery.storage.db import dispose_engine, init_engine
from telegram_lead_discovery.storage.jobs import recover_stale_jobs
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import Job
from telegram_lead_discovery.storage.session import configure_session_factory, run_write


@pytest.fixture
async def db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("TG_API_ID", "12345")
    monkeypatch.setenv("TG_API_HASH", "hash-for-tests")
    for name in ("TG_BOT_TOKEN", "TG_NOTIFY_CHAT_ID"):
        monkeypatch.delenv(name, raising=False)
    paths = ensure_app_directories(resolve_app_paths())
    upgrade_head(paths.database_path)
    engine = await init_engine(paths.database_path)
    configure_session_factory(engine)
    await run_write(seed_defaults)
    yield paths
    await dispose_engine()
    from telegram_lead_discovery.storage.session import reset_write_lock

    reset_write_lock()


@pytest.mark.asyncio
async def test_coordinator_starts_named_loops_not_deferred(db_env) -> None:
    registry = reset_health_registry()
    registry.set_component("runtime", HealthState.STARTING)
    gateway = FakeTelegramGateway()

    coordinator = RuntimeCoordinator(idle_seconds=0.05, periodic_reconcile_seconds=3600)
    await coordinator.start(registry, gateway=gateway)

    loops = coordinator.named_loops_running()
    assert loops["keyword_discovery"] is True
    assert loops["graph_discovery"] is True
    assert loops["collector_jobs"] is True
    assert loops["live_updates"] is True
    assert loops["processing"] is True
    assert loops["notifications"] is True
    assert loops["reconciliation"] is True
    assert loops["watchdog"] is True

    collector = registry.components["collector"]
    assert collector.state is HealthState.HEALTHY
    assert collector.reason_code != "deferred"
    assert collector.state is not HealthState.STOPPED

    assert PERIODIC_RECONCILE_SECONDS == 15 * 60

    await coordinator.shutdown()
    assert coordinator.named_loops_running()["keyword_discovery"] is False


@pytest.mark.asyncio
async def test_one_loop_failure_does_not_kill_siblings(db_env) -> None:
    registry = reset_health_registry()
    gateway = FakeTelegramGateway()
    coordinator = RuntimeCoordinator(idle_seconds=0.05, periodic_reconcile_seconds=3600)
    await coordinator.start(registry, gateway=gateway)

    async def _boom(stop: asyncio.Event) -> None:
        raise RuntimeError("injected_collector_failure")

    # Replace collector job body with a failing one-shot; watchdog should restart.
    assert coordinator.collector_job_loop is not None
    await coordinator.collector_job_loop.stop()
    coordinator.collector_job_loop = SupervisedLoop(
        name="collector-job-loop",
        factory=lambda: _boom,
        idle_seconds=0.05,
    )
    coordinator.collector_job_loop.start()
    await asyncio.sleep(0.05)
    assert coordinator.collector_job_loop.task is not None
    assert coordinator.collector_job_loop.task.done()

    # Sibling loops still alive.
    assert coordinator.worker_running is True
    assert coordinator.processing_loop is not None
    assert coordinator.processing_loop.task is not None
    assert not coordinator.processing_loop.task.done()

    await coordinator._watchdog_tick()
    assert coordinator.collector_job_loop.running is True

    await coordinator.shutdown()


@pytest.mark.asyncio
async def test_startup_enqueues_reconciliation_and_recovers_stale_jobs(db_env) -> None:
    snap = make_source(telegram_id=7001, username="wave06_src")
    gateway = FakeTelegramGateway(sources={"wave06_src": snap})

    async def _add(session):
        source, _ = await add_manual_candidate(
            session, username_or_url="@wave06_src", gateway=gateway
        )
        return source.id

    source_id = await run_write(_add)

    async def _approve(session):
        return await approve_source(session, source_id=source_id, gateway=gateway)

    await run_write(_approve)

    registry = reset_health_registry()
    coordinator = RuntimeCoordinator(
        idle_seconds=0.05,
        periodic_reconcile_seconds=3600,
        startup_token="boot-test-1",
    )
    await coordinator.start(registry, gateway=gateway)

    async def _jobs(session):
        rows = list((await session.execute(select(Job))).scalars())
        return [(j.job_type, j.state, j.dedupe_key) for j in rows]

    jobs = await run_write(_jobs)
    types = {t for t, _s, _d in jobs}
    assert "initial_backfill" in types
    assert "startup_reconciliation" in types

    # Stop collector so it cannot reclaim before we assert lease recovery.
    if coordinator.collector_job_loop is not None:
        await coordinator.collector_job_loop.stop()

    async def _expire(session):
        result = await session.execute(select(Job).order_by(Job.id.asc()).limit(1))
        job = result.scalar_one()
        job.state = "running"
        job.lease_until = datetime.now(UTC) - timedelta(seconds=10)
        await session.flush()
        return job.id

    job_id = await run_write(_expire)
    recovered = await run_write(recover_stale_jobs)
    assert recovered >= 1

    async def _state(session):
        job = await session.get(Job, job_id)
        assert job is not None
        return job.state

    assert await run_write(_state) == "queued"
    await coordinator.shutdown()


@pytest.mark.asyncio
async def test_notification_disabled_loop_stays_healthy(db_env) -> None:
    registry = reset_health_registry()
    gateway = FakeTelegramGateway()
    coordinator = RuntimeCoordinator(idle_seconds=0.05, periodic_reconcile_seconds=3600)
    await coordinator.start(registry, gateway=gateway)

    assert coordinator.notification_loop is not None
    assert isinstance(coordinator.notification_loop, NotificationOutboxLoop)
    # Wait until the loop has observed shadow mode at least once.
    for _ in range(50):
        if coordinator.notification_loop.delivery_disabled:
            break
        await asyncio.sleep(0.05)
    assert coordinator.notification_loop.delivery_disabled is True
    assert registry.components["notifications"].state in {
        HealthState.HEALTHY,
        HealthState.DEGRADED,
    }
    assert registry.components["notifications"].state is not HealthState.STOPPED
    await coordinator.shutdown()


@pytest.mark.asyncio
async def test_second_start_does_not_duplicate_workers(db_env) -> None:
    registry = reset_health_registry()
    gateway = FakeTelegramGateway()
    coordinator = RuntimeCoordinator(idle_seconds=0.05, periodic_reconcile_seconds=3600)
    await coordinator.start(registry, gateway=gateway)
    first_task = coordinator.discovery_loop.task if coordinator.discovery_loop else None
    await coordinator.start(registry, gateway=gateway)
    second_task = coordinator.discovery_loop.task if coordinator.discovery_loop else None
    assert first_task is second_task
    await coordinator.shutdown()


@pytest.mark.asyncio
async def test_enqueue_startup_reconciliation_helper(db_env) -> None:
    snap = make_source(telegram_id=7002, username="recon_src")
    gateway = FakeTelegramGateway(sources={"recon_src": snap})

    async def _seed(session):
        source, _ = await add_manual_candidate(
            session, username_or_url="@recon_src", gateway=gateway
        )
        await approve_source(session, source_id=source.id, gateway=gateway)
        return await enqueue_startup_reconciliation(session, startup_token="t1")

    count = await run_write(_seed)
    assert count == 1
