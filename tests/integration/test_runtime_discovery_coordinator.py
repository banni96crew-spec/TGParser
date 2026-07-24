"""Integration — runtime coordinator + discovery claim loop (INF-021 / AT-INF-021)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from telegram_lead_discovery.collector.fake import FakeTelegramGateway
from telegram_lead_discovery.infrastructure.paths import database_path, ensure_directories
from telegram_lead_discovery.infrastructure.runtime import (
    START_DISABLED_TELEGRAM_CREDENTIALS_MISSING,
    RuntimeCoordinator,
)
from telegram_lead_discovery.observability.health import (
    HealthState,
    get_health_registry,
    reset_health_registry,
)
from telegram_lead_discovery.source_discovery.worker import KeywordDiscoveryClaimLoop
from telegram_lead_discovery.storage.db import dispose_engine, init_engine
from telegram_lead_discovery.storage.migrate import upgrade_head


@pytest.fixture
async def db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    # Ensure secret presence is controlled by each test.
    for name in ("TG_API_ID", "TG_API_HASH", "TG_BOT_TOKEN", "TG_NOTIFY_CHAT_ID"):
        monkeypatch.delenv(name, raising=False)
    ensure_directories()
    db_path = database_path()
    upgrade_head(db_path)
    await init_engine(db_path)
    yield db_path
    await dispose_engine()


@pytest.mark.asyncio
async def test_coordinator_blocks_discovery_without_credentials(db_env, monkeypatch) -> None:
    registry = reset_health_registry()
    registry.set_component("runtime", HealthState.STARTING)

    coordinator = RuntimeCoordinator()
    await coordinator.start(registry)

    assert coordinator.credentials_present is False
    assert coordinator.start_disabled_reason == START_DISABLED_TELEGRAM_CREDENTIALS_MISSING
    assert coordinator.gateway is None
    assert coordinator.worker_running is False
    discovery = registry.components["discovery"]
    assert discovery.state is HealthState.BLOCKED
    assert discovery.reason_code == START_DISABLED_TELEGRAM_CREDENTIALS_MISSING


@pytest.mark.asyncio
async def test_coordinator_starts_shared_gateway_worker(db_env, monkeypatch) -> None:
    monkeypatch.setenv("TG_API_ID", "12345")
    monkeypatch.setenv("TG_API_HASH", "hash-for-tests")

    registry = reset_health_registry()
    registry.set_component("runtime", HealthState.STARTING)
    gateway = FakeTelegramGateway()

    coordinator = RuntimeCoordinator()
    await coordinator.start(registry, gateway=gateway)

    assert coordinator.credentials_present is True
    assert coordinator.start_disabled_reason is None
    assert coordinator.gateway is gateway
    assert coordinator.worker_running is True
    assert registry.components["discovery"].state is HealthState.HEALTHY

    # Shared gateway identity for dashboard / future collector.
    assert coordinator.gateway is gateway

    await coordinator.shutdown()
    assert coordinator.worker_running is False
    assert coordinator.gateway is None
    assert registry.components["discovery"].state is HealthState.STOPPED
    assert registry.components["discovery"].reason_code == "worker_stopped"


@pytest.mark.asyncio
async def test_claim_loop_stop_awaits_idle_cycle(db_env) -> None:
    gateway = FakeTelegramGateway()
    loop = KeywordDiscoveryClaimLoop(gateway, idle_seconds=0.05)
    task = loop.start()
    assert not task.done()

    # Allow at least one empty claim + idle wait.
    await asyncio.sleep(0.12)
    await loop.stop()
    assert loop.task is None
    assert task.done()


@pytest.mark.asyncio
async def test_runtime_healthy_after_worker_when_credentials_present(
    db_env, monkeypatch
) -> None:
    monkeypatch.setenv("TG_API_ID", "12345")
    monkeypatch.setenv("TG_API_HASH", "hash-for-tests")

    registry = reset_health_registry()
    registry.migration_ok = True
    registry.integrity_ok = True
    registry.database_ok = True
    registry.mark_ready()
    registry.set_component("runtime", HealthState.STARTING)

    coordinator = RuntimeCoordinator()
    await coordinator.start(registry, gateway=FakeTelegramGateway())
    # INF-021: mark runtime healthy only after worker start path.
    registry.set_component("runtime", HealthState.HEALTHY)

    assert get_health_registry().components["runtime"].state is HealthState.HEALTHY
    assert get_health_registry().components["discovery"].state is HealthState.HEALTHY
    await coordinator.shutdown()
