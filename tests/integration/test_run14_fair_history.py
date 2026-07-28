"""Focused RUN14 revise: fair history waterfill + run-cap gate inconclusive."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from telegram_lead_discovery.collector.fake import FakeTelegramGateway, make_source
from telegram_lead_discovery.collector.ports import TelegramMessageDTO
from telegram_lead_discovery.infrastructure.paths import database_path, ensure_directories
from telegram_lead_discovery.source_discovery import worker as worker_mod
from telegram_lead_discovery.source_discovery.keyword_run import start_keyword_discovery_run
from telegram_lead_discovery.source_discovery.profile_service import (
    create_keyword_discovery_profile,
)
from telegram_lead_discovery.source_discovery.worker import (
    claim_and_process_keyword_job,
    process_keyword_discovery_job,
)
from telegram_lead_discovery.storage.db import dispose_engine, init_engine, session_scope
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import (
    DiscoveryRun,
    DiscoveryRunQuery,
    Job,
    SourceDiscoveryEvidence,
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


def _fresh(hours: int = 1) -> datetime:
    return datetime.now(UTC) - timedelta(hours=hours)


def _noise(n: int) -> str:
    return f"Сегодня отличная погода вариант {n}"


def _client(n: int) -> str:
    return f"Нужно разработать интернет-магазин номер {n}, бюджет 150 000 ₽."


@pytest.mark.asyncio
async def test_fair_waterfill_probes_later_sources_before_early_source_cap(
    db_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With >N candidates and tight run budget, later sources get pages before early hits cap."""
    monkeypatch.setattr(worker_mod, "HISTORY_SCAN_CAP_PER_RUN", 400)
    monkeypatch.setattr(worker_mod, "HISTORY_SCAN_CAP_PER_SOURCE", 300)
    monkeypatch.setattr(worker_mod, "HISTORY_PAGE_SIZE", 50)

    gw = FakeTelegramGateway()
    sources = []
    for i in range(1, 6):
        src = make_source(
            telegram_id=9000 + i,
            username=f"pool_chat_{i}",
            source_type="megagroup",
            title=f"Pool Chat {i}",
        )
        sources.append(src)
        gw.register_source(src.username, src)
        if i == 3:
            # Promising middle source: client asks first, then noise.
            msgs = [
                TelegramMessageDTO(
                    schema_version=1,
                    source_id=0,
                    telegram_message_id=20000 - j,
                    published_at=_fresh(j),
                    text=_client(j + 1),
                    telegram_peer_id=src.telegram_id,
                    permalink=f"https://t.me/{src.username}/{20000 - j}",
                )
                for j in range(8)
            ] + [
                TelegramMessageDTO(
                    schema_version=1,
                    source_id=0,
                    telegram_message_id=15000 - j,
                    published_at=_fresh(20 + j),
                    text=_noise(j),
                    telegram_peer_id=src.telegram_id,
                )
                for j in range(300)
            ]
        else:
            msgs = [
                TelegramMessageDTO(
                    schema_version=1,
                    source_id=0,
                    telegram_message_id=10000 - j,
                    published_at=_fresh(j % 20),
                    text=_noise(j),
                    telegram_peer_id=src.telegram_id,
                    permalink=f"https://t.me/{src.username}/{10000 - j}",
                )
                for j in range(350)
            ]
        gw.register_messages_for_peer(src.telegram_id, msgs)

    gw.set_directory_results(sources)
    gw.set_quota(free_slot_available=False, premium_required=False, stars_amount=0)
    gw.set_global_hits([])

    async with session_scope() as session:
        profile = await create_keyword_discovery_profile(
            session,
            name="fair-waterfill",
            post_queries=["нужен сайт"],
            directory_queries=["pool"],
            source_scope="groups",
        )
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        run_id = started.run.id
        job_id = started.job.id

    async with session_scope() as session:
        job = await session.get(Job, job_id)
        await process_keyword_discovery_job(session, job, gw)  # type: ignore[arg-type]

    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        assert run is not None
        counters = json.loads(run.counters_json or "{}")
        assert int(counters.get("history_scanned_total") or 0) == 400
        queries = list(
            (
                await session.execute(
                    select(DiscoveryRunQuery).where(
                        DiscoveryRunQuery.run_id == run_id,
                        DiscoveryRunQuery.query_kind == "source_verification",
                    )
                )
            )
            .scalars()
            .all()
        )
        scanned_by: dict[int, int] = {}
        for q in queries:
            cur = json.loads(q.cursor_json or "{}")
            scanned_by[int(q.source_telegram_id)] = int(cur.get("scanned") or 0)

        assert len(scanned_by) >= 4
        assert scanned_by.get(9001, 0) < 300
        assert scanned_by.get(9005, 0) > 0
        assert scanned_by.get(9003, 0) > 0
        if not counters.get("pool_exhausted"):
            assert counters.get("gate_status") == "inconclusive"


@pytest.mark.asyncio
async def test_flood_mid_fair_page_persists_cursor_and_resumes(
    db_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker_mod, "HISTORY_PAGE_SIZE", 20)

    gw = FakeTelegramGateway()
    src = make_source(
        telegram_id=4401,
        username="fair_flood",
        source_type="megagroup",
        title="Fair Flood Chat",
    )
    gw.register_source("fair_flood", src)
    gw.set_directory_results([src])
    gw.set_quota(free_slot_available=False)
    gw.set_global_hits([])
    gw.register_messages_for_peer(
        4401,
        [
            TelegramMessageDTO(
                schema_version=1,
                source_id=0,
                telegram_message_id=500 - i,
                published_at=_fresh(i),
                text=_client(i + 1),
                telegram_peer_id=4401,
            )
            for i in range(40)
        ],
    )

    async with session_scope() as session:
        profile = await create_keyword_discovery_profile(
            session,
            name="fair-flood",
            post_queries=["нужен сайт"],
            directory_queries=["fair"],
            source_scope="groups",
        )
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        run_id = started.run.id
        job_id = started.job.id

    until = datetime.now(UTC) + timedelta(minutes=5)
    gw.set_flood_wait(until, "iter_history")

    async with session_scope() as session:
        job = await session.get(Job, job_id)
        await process_keyword_discovery_job(session, job, gw)  # type: ignore[arg-type]

    async with session_scope() as session:
        q = (
            await session.execute(
                select(DiscoveryRunQuery).where(
                    DiscoveryRunQuery.run_id == run_id,
                    DiscoveryRunQuery.query_kind == "source_verification",
                )
            )
        ).scalars().first()
        assert q is not None
        assert q.state == "retry_wait"
        cursor = json.loads(q.cursor_json or "{}")
        assert cursor.get("stop_reason") == "flood_wait"
        scanned_before = int(cursor.get("scanned") or 0)
        run = await session.get(DiscoveryRun, run_id)
        assert run is not None
        payload = json.loads(run.cursor_json or "{}")
        assert payload.get("acquisition_pool")

    gw.clear_flood_wait()
    async with session_scope() as session:
        q = (
            await session.execute(
                select(DiscoveryRunQuery).where(
                    DiscoveryRunQuery.run_id == run_id,
                    DiscoveryRunQuery.query_kind == "source_verification",
                )
            )
        ).scalars().first()
        assert q is not None
        q.available_at = datetime.now(UTC) - timedelta(seconds=1)
        q.state = "retry_wait"
        job = (await session.execute(select(Job).where(Job.id == job_id))).scalar_one()
        job.state = "queued"
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.flush()

    async with session_scope() as session:
        await claim_and_process_keyword_job(session, gw)

    async with session_scope() as session:
        q = (
            await session.execute(
                select(DiscoveryRunQuery).where(
                    DiscoveryRunQuery.run_id == run_id,
                    DiscoveryRunQuery.query_kind == "source_verification",
                )
            )
        ).scalars().first()
        assert q is not None
        cursor = json.loads(q.cursor_json or "{}")
        assert int(cursor.get("scanned") or 0) >= scanned_before
        rows = list(
            (
                await session.execute(
                    select(SourceDiscoveryEvidence).where(
                        SourceDiscoveryEvidence.run_id == run_id
                    )
                )
            )
            .scalars()
            .all()
        )
        ids = [r.telegram_message_id for r in rows]
        assert len(ids) == len(set(ids))
