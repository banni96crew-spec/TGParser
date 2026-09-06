"""AT-SRC-055 — operator_seed resolve after SEARCH, no linked discussion."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from telegram_lead_discovery.collector.fake import FakeTelegramGateway, make_source
from telegram_lead_discovery.infrastructure.paths import database_path, ensure_directories
from telegram_lead_discovery.source_discovery.keyword_run import start_keyword_discovery_run
from telegram_lead_discovery.source_discovery.profile_service import (
    create_keyword_discovery_profile,
)
from telegram_lead_discovery.source_discovery.worker import claim_and_process_keyword_job
from telegram_lead_discovery.storage.db import dispose_engine, init_engine, session_scope
from telegram_lead_discovery.storage.dismissed_suppress import (
    SuppressIdentity,
    peer_canonical_key,
)
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import (
    DiscoveryRun,
    DiscoveryRunQuery,
    TelegramSource,
)
from telegram_lead_discovery.storage.presented_suppress import upsert_presented_suppress


@pytest.fixture
async def db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    ensure_directories()
    db_path = database_path()
    upgrade_head(db_path)
    await init_engine(db_path)
    yield db_path
    await dispose_engine()


async def _profile(session, *, name: str):
    return await create_keyword_discovery_profile(
        session,
        name=name,
        post_queries=["нужен сайт"],
        directory_queries=[],
        replacement_directory_queries=[],
        source_scope="groups",
    )


def _gateway() -> FakeTelegramGateway:
    gw = FakeTelegramGateway()
    gw.register_source(
        "chat_ok",
        make_source(
            telegram_id=71001,
            username="chat_ok",
            title="OK Chat",
            source_type="megagroup",
        ),
    )
    gw.register_source(
        "news_chan",
        make_source(
            telegram_id=71002,
            username="news_chan",
            title="News",
            source_type="channel",
        ),
    )
    gw.set_global_hits([])
    gw.set_directory_results([])
    gw.set_quota(free_slot_available=True)
    gw.set_public_post_hits("нужен сайт", [])
    return gw


@pytest.mark.asyncio
async def test_at_src_055_resolve_skips_channel_invite_without_linked(db_env) -> None:
    gw = _gateway()
    async with session_scope() as session:
        profile = await _profile(session, name="seed-resolve")
        started = await start_keyword_discovery_run(
            session,
            profile_id=profile.profile.id,
            seed_refs=(
                "@chat_ok",
                "@news_chan",
                "https://t.me/+R_KxUQG5hYo5ZjAy",
            ),
        )
        run_id = started.run.id

    async with session_scope() as session:
        outcome = await claim_and_process_keyword_job(session, gw)
        assert outcome is not None

    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        assert run is not None
        counters = json.loads(run.counters_json or "{}")
        assert int(counters.get("operator_seed_skipped") or 0) >= 2
        seeds = list(
            (
                await session.execute(
                    select(DiscoveryRunQuery).where(
                        DiscoveryRunQuery.run_id == run_id,
                        DiscoveryRunQuery.query_kind == "operator_seed",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(seeds) == 3
        assert all(row.state == "succeeded" for row in seeds)
        cursor = json.loads(run.cursor_json or "{}")
        pool = cursor.get("acquisition_pool") or []
        pool_ids = {int(item["telegram_id"]) for item in pool if "telegram_id" in item}
        assert 71001 in pool_ids
        lanes = {
            int(item["telegram_id"]): item.get("selected_lane")
            for item in pool
            if "telegram_id" in item
        }
        assert lanes.get(71001) == "OPERATOR_SEED"
        assert 71002 not in pool_ids
        source_count = int(
            await session.scalar(select(func.count()).select_from(TelegramSource)) or 0
        )
        assert source_count == 0
    assert gw.get_linked_discussion_calls == []


@pytest.mark.asyncio
async def test_at_src_055_quality_seed_is_not_scanned(db_env) -> None:
    gw = _gateway()
    async with session_scope() as session:
        await upsert_presented_suppress(
            session,
            identity=SuppressIdentity(
                canonical_key=peer_canonical_key(71001),
                telegram_id=71001,
                username_normalized="chat_ok",
            ),
            origin_run_id=1,
            suppress_class="quality",
        )
        profile = await _profile(session, name="seed-quality")
        started = await start_keyword_discovery_run(
            session,
            profile_id=profile.profile.id,
            seed_refs=("@chat_ok",),
        )
        run_id = started.run.id

    async with session_scope() as session:
        await claim_and_process_keyword_job(session, gw)

    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        assert run is not None
        counters = json.loads(run.counters_json or "{}")
        assert int(counters.get("presented_suppressed") or 0) >= 1
        cursor = json.loads(run.cursor_json or "{}")
        pool_ids = {
            int(item["telegram_id"])
            for item in (cursor.get("acquisition_pool") or [])
            if "telegram_id" in item
        }
        assert 71001 not in pool_ids
        verified = list(
            (
                await session.execute(
                    select(DiscoveryRunQuery).where(
                        DiscoveryRunQuery.run_id == run_id,
                        DiscoveryRunQuery.query_kind == "source_verification",
                        DiscoveryRunQuery.source_telegram_id == 71001,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert verified == []
    assert gw.get_linked_discussion_calls == []


@pytest.mark.asyncio
async def test_at_src_055_non_quality_ledger_does_not_block_seed(db_env) -> None:
    gw = _gateway()
    async with session_scope() as session:
        await upsert_presented_suppress(
            session,
            identity=SuppressIdentity(
                canonical_key=peer_canonical_key(71001),
                telegram_id=71001,
                username_normalized="chat_ok",
            ),
            origin_run_id=1,
            suppress_class="non_quality",
        )
        await upsert_presented_suppress(
            session,
            identity=SuppressIdentity(
                canonical_key=peer_canonical_key(71003),
                telegram_id=71003,
                username_normalized="legacy_chat",
            ),
            origin_run_id=1,
            suppress_class="legacy_unspecified",
        )
        profile = await _profile(session, name="seed-non-quality")
        started = await start_keyword_discovery_run(
            session,
            profile_id=profile.profile.id,
            seed_refs=("@chat_ok",),
        )
        run_id = started.run.id

    async with session_scope() as session:
        await claim_and_process_keyword_job(session, gw)

    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        assert run is not None
        counters = json.loads(run.counters_json or "{}")
        assert int(counters.get("presented_suppressed") or 0) == 0
        cursor = json.loads(run.cursor_json or "{}")
        pool_ids = {
            int(item["telegram_id"])
            for item in (cursor.get("acquisition_pool") or [])
            if "telegram_id" in item
        }
        assert 71001 in pool_ids
    assert gw.get_linked_discussion_calls == []
