from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from telegram_lead_discovery.collector.fake import FakeTelegramGateway
from telegram_lead_discovery.collector.ports import TelegramMessageDTO
from telegram_lead_discovery.detection.seed import seed_active_ruleset
from telegram_lead_discovery.infrastructure.paths import ensure_app_directories, resolve_app_paths
from telegram_lead_discovery.processing.history_scan import (
    HistoryScanError,
    claim_and_process_history_scan_job,
    create_history_scan,
)
from telegram_lead_discovery.settings.service import seed_defaults
from telegram_lead_discovery.storage.db import dispose_engine, init_engine
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import (
    HistoryScanResult,
    HistoryScanSession,
    Lead,
    TelegramSource,
)
from telegram_lead_discovery.storage.retention import run_retention_purge
from telegram_lead_discovery.storage.session import configure_session_factory, run_write


@pytest.fixture
async def db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    paths = ensure_app_directories(resolve_app_paths())
    upgrade_head(paths.database_path)
    engine = await init_engine(paths.database_path)
    configure_session_factory(engine)

    async def seed(session):
        await seed_defaults(session)
        await seed_active_ruleset(session)

    await run_write(seed)
    yield paths
    await dispose_engine()


@pytest.mark.asyncio
async def test_scan_keeps_vacancy_and_client_request_without_creating_lead(db_env) -> None:
    now = datetime.now(UTC)

    async def add_source(session):
        source = TelegramSource(
            telegram_id=701,
            username_normalized="history_scan_source",
            title="История",
            source_type="megagroup",
            lifecycle_state="monitoring",
            quality_score=2,
        )
        session.add(source)
        await session.flush()
        return source.id

    source_id = await run_write(add_source)
    gateway = FakeTelegramGateway()
    gateway.register_messages_for_peer(
        701,
        [
            TelegramMessageDTO(
                schema_version=2,
                source_id=source_id,
                telegram_message_id=2,
                published_at=now - timedelta(hours=1),
                text="Вакансия: Python-разработчик в штат, зарплата 200000.",
                telegram_peer_id=701,
                permalink="https://t.me/history_scan_source/2",
            ),
            TelegramMessageDTO(
                schema_version=2,
                source_id=source_id,
                telegram_message_id=1,
                published_at=now - timedelta(hours=2),
                text="Нужен сайт для магазина, ищу исполнителя",
                telegram_peer_id=701,
                permalink="https://t.me/history_scan_source/1",
            ),
        ],
    )

    scan = await run_write(
        lambda session: create_history_scan(
            session, source_ids=[source_id], period_hours=24, now=now
        )
    )
    assert scan.state == "queued"
    assert await claim_and_process_history_scan_job(gateway) == "processed"

    async def rows(session):
        scan_row = await session.get(HistoryScanSession, scan.id)
        results = list(
            (await session.execute(select(HistoryScanResult))).scalars()
        )
        leads = list((await session.execute(select(Lead))).scalars())
        return scan_row, results, leads

    scan_row, results, leads = await run_write(rows)
    assert scan_row is not None and scan_row.state == "succeeded"
    assert {row.category for row in results} >= {"vacancy", "direct_order"}
    assert leads == []
    assert all("Нужен" not in row.explanation_json for row in results)


@pytest.mark.asyncio
async def test_scan_rejects_period_over_48_hours(db_env) -> None:
    async def create(session):
        with pytest.raises(HistoryScanError, match="period_hours_must_be_1_to_48"):
            await create_history_scan(session, source_ids=[1], period_hours=49)

    await run_write(create)


@pytest.mark.asyncio
async def test_retention_removes_scan_results_after_24_hours(db_env) -> None:
    now = datetime.now(UTC)

    async def add_source_and_scan(session):
        source = TelegramSource(
            telegram_id=702,
            username_normalized="history_retention_source",
            title="Очистка",
            source_type="megagroup",
            lifecycle_state="monitoring",
        )
        session.add(source)
        await session.flush()
        return await create_history_scan(
            session, source_ids=[source.id], period_hours=1, now=now
        ), source.id

    scan, source_id = await run_write(add_source_and_scan)
    gateway = FakeTelegramGateway()
    gateway.register_messages_for_peer(
        702,
        [
            TelegramMessageDTO(
                schema_version=2,
                source_id=source_id,
                telegram_message_id=1,
                published_at=now - timedelta(minutes=10),
                text="Вакансия: Python-разработчик в штат, зарплата 200000.",
                telegram_peer_id=702,
            )
        ],
    )
    await claim_and_process_history_scan_job(gateway)

    async def purge(session):
        return await run_retention_purge(session, now=now + timedelta(hours=24, seconds=1))

    result = await run_write(purge)
    assert result.history_scan_results_deleted == 1
    assert scan.id
