"""E2E — FakeGateway keyword discovery journey (plan §18).

seed profile → start run → fake search → linked discussion → evidence →
ranked → promote → candidate → approve → backfill → processing → Lead.

No live Telegram credentials.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from telegram_lead_discovery.collector.fake import (
    FakeTelegramGateway,
    make_hit,
    make_source,
)
from telegram_lead_discovery.collector.ports import TelegramMessageDTO
from telegram_lead_discovery.collector.service import handle_backfill_job
from telegram_lead_discovery.detection.seed import seed_ruleset_ru_mvp_1
from telegram_lead_discovery.infrastructure.paths import ensure_app_directories, resolve_app_paths
from telegram_lead_discovery.processing.pipeline import process_next_envelope
from telegram_lead_discovery.settings.service import seed_defaults
from telegram_lead_discovery.source_discovery.keyword_profiles import SEED_PROFILE_NAME
from telegram_lead_discovery.source_discovery.keyword_run import start_keyword_discovery_run
from telegram_lead_discovery.source_discovery.profile_service import ensure_seed_keyword_profile
from telegram_lead_discovery.source_discovery.promotion import promote_opportunity_to_candidate
from telegram_lead_discovery.source_discovery.service import approve_source
from telegram_lead_discovery.source_discovery.worker import claim_and_process_keyword_job
from telegram_lead_discovery.storage.db import dispose_engine, init_engine
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import (
    CollectorCheckpoint,
    DiscoveryRun,
    Job,
    Lead,
    NotificationOutbox,
    SourceDiscoveryEvidence,
    SourceOpportunitySnapshot,
    TelegramEventEnvelope,
    TelegramMessage,
    TelegramSource,
)
from telegram_lead_discovery.storage.session import configure_session_factory, run_write

HOT_TEXT = (
    "Нужно разработать интернет-магазин с оплатой и корзиной, "
    "бюджет 250000 ₽, срочно, готов начать, пишите @leadclient12."
)

# Contains first seed post-query so FakeGateway global filter matches.
SCOUT_EXCERPT = (
    "нужен разработчик сайта — нужно разработать интернет-магазин, "
    "бюджет 150000 ₽"
)


@pytest.fixture
async def e2e_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("TG_API_ID", "12345")
    monkeypatch.setenv("TG_API_HASH", "hash-for-e2e-fake")
    paths = ensure_app_directories(resolve_app_paths())
    upgrade_head(paths.database_path)
    engine = await init_engine(paths.database_path)
    configure_session_factory(engine)

    async def _seed(session):
        await seed_defaults(session)
        await seed_ruleset_ru_mvp_1(session)
        return await ensure_seed_keyword_profile(session)

    seed = await run_write(_seed)
    yield paths, seed
    await dispose_engine()


def _fresh(hours: int = 2) -> datetime:
    return datetime.now(UTC) - timedelta(hours=hours)


def _build_gateway() -> FakeTelegramGateway:
    gw = FakeTelegramGateway()
    group = make_source(
        telegram_id=501,
        username="dev_chat_e2e",
        source_type="megagroup",
        title="Dev Chat E2E",
    )
    channel = make_source(
        telegram_id=502,
        username="shop_news_e2e",
        source_type="channel",
        title="ecommerce shop news",
    )
    discussion = make_source(
        telegram_id=503,
        username="shop_discuss_e2e",
        source_type="megagroup",
        title="Shop Discuss E2E",
    )
    gw.register_source("dev_chat_e2e", group)
    gw.register_source("shop_news_e2e", channel)
    gw.register_source("shop_discuss_e2e", discussion)
    gw.set_global_hits(
        [
            make_hit(
                source=group,
                message_id=11,
                excerpt=SCOUT_EXCERPT,
                published_at=_fresh(),
            ),
            make_hit(
                source=channel,
                message_id=22,
                excerpt=SCOUT_EXCERPT,
                published_at=_fresh(3),
            ),
        ]
    )
    gw.set_directory_results([group, channel])
    gw.set_quota(free_slot_available=True)
    gw.set_public_post_hits(
        "нужен разработчик сайта",
        [
            make_hit(
                source=channel,
                message_id=33,
                excerpt=SCOUT_EXCERPT,
                published_at=_fresh(4),
            )
        ],
    )
    gw.set_linked_discussion(502, discussion)
    gw.set_source_message_hits(
        501,
        [
            make_hit(
                source=group,
                message_id=44,
                excerpt=SCOUT_EXCERPT,
                published_at=_fresh(1),
            )
        ],
    )
    gw.set_source_message_hits(
        502,
        [
            make_hit(
                source=channel,
                message_id=55,
                excerpt=SCOUT_EXCERPT,
                published_at=_fresh(1),
            )
        ],
    )
    return gw


@pytest.mark.asyncio
async def test_fake_gateway_keyword_discovery_e2e_to_lead(e2e_env) -> None:
    _paths, seed = e2e_env
    assert seed.profile.name == SEED_PROFILE_NAME
    gw = _build_gateway()

    async def _start(session):
        return await start_keyword_discovery_run(
            session, profile_id=seed.profile.id, credentials_present=True
        )

    started = await run_write(_start)
    run_id = started.run.id
    assert started.run.run_type == "keyword_scouting"
    assert started.run.search_mode == "free_only"
    assert started.query_count > 0

    async def _assert_isolation_before(session):
        assert (
            await session.execute(select(func.count()).select_from(TelegramMessage))
        ).scalar_one() == 0
        assert (
            await session.execute(select(func.count()).select_from(Lead))
        ).scalar_one() == 0
        assert (
            await session.execute(select(func.count()).select_from(NotificationOutbox))
        ).scalar_one() == 0
        assert (
            await session.execute(select(func.count()).select_from(CollectorCheckpoint))
        ).scalar_one() == 0

    await run_write(_assert_isolation_before)

    async def _worker(session):
        return await claim_and_process_keyword_job(session, gw)

    outcome = await run_write(_worker)
    assert outcome is not None
    assert outcome["outcome"] in ("succeeded", "partial")

    async def _after_scout(session):
        run = await session.get(DiscoveryRun, run_id)
        assert run is not None
        assert run.state in ("succeeded", "partial")
        evidence_n = (
            await session.execute(
                select(func.count())
                .select_from(SourceDiscoveryEvidence)
                .where(SourceDiscoveryEvidence.run_id == run_id)
            )
        ).scalar_one()
        assert evidence_n >= 1
        snaps = list(
            (
                await session.execute(
                    select(SourceOpportunitySnapshot)
                    .where(SourceOpportunitySnapshot.run_id == run_id)
                    .order_by(
                        SourceOpportunitySnapshot.score.desc(),
                        SourceOpportunitySnapshot.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert snaps
        linked = [s for s in snaps if s.linked_parent_telegram_id == 502]
        assert linked
        assert linked[0].source_telegram_id == 503
        # Discovery isolation: still no pipeline entities.
        assert (
            await session.execute(select(func.count()).select_from(TelegramMessage))
        ).scalar_one() == 0
        assert (
            await session.execute(select(func.count()).select_from(Lead))
        ).scalar_one() == 0
        assert (
            await session.execute(select(func.count()).select_from(TelegramEventEnvelope))
        ).scalar_one() == 0
        top = snaps[0]
        return top.id, top.version

    top_opp_id, top_version = await run_write(_after_scout)

    async def _promote(session):
        result = await promote_opportunity_to_candidate(
            session,
            opportunity_id=top_opp_id,
            version=top_version,
        )
        assert result.source.lifecycle_state == "candidate"
        assert result.snapshot.review_state == "promoted"
        assert result.created_new is True
        return result.source.id

    source_id = await run_write(_promote)

    async def _register_backfill_messages(session):
        source = await session.get(TelegramSource, source_id)
        assert source is not None
        assert source.telegram_id is not None
        snap = gw._sources_by_id.get(source.telegram_id)
        if snap is None:
            snap = make_source(
                telegram_id=source.telegram_id,
                username=source.username_normalized or f"src_{source.telegram_id}",
                source_type=source.source_type or "channel",
                title=source.title or "E2E",
            )
            gw.register_source(snap.username, snap)
        now = datetime.now(UTC)
        gw.register_messages(
            source_id,
            [
                TelegramMessageDTO(
                    schema_version=1,
                    source_id=source_id,
                    telegram_message_id=1001,
                    published_at=now,
                    text=HOT_TEXT,
                    permalink=f"https://t.me/{snap.username}/1001",
                )
            ],
        )
        return source_id

    await run_write(_register_backfill_messages)

    async def _approve(session):
        return await approve_source(session, source_id=source_id, gateway=gw)

    approved = await run_write(_approve)
    assert approved.lifecycle_state == "monitoring"

    async def _backfill_job(session):
        job = (
            await session.execute(
                select(Job).where(
                    Job.job_type == "initial_backfill",
                    Job.dedupe_key == f"initial_backfill:{source_id}",
                )
            )
        ).scalar_one()
        assert job.state == "queued"
        return await handle_backfill_job(session, job, gw)

    backfill = await run_write(_backfill_job)
    assert backfill["outcome"] == "succeeded"
    assert backfill["persisted"] >= 1

    async def _process_to_lead(session):
        envelopes = list(
            (await session.execute(select(TelegramEventEnvelope))).scalars().all()
        )
        assert envelopes
        assert any(e.processing_state == "queued" for e in envelopes)
        result = await process_next_envelope(
            session, owner="keyword-e2e", now=datetime.now(UTC)
        )
        leads = list((await session.execute(select(Lead))).scalars().all())
        messages = list(
            (
                await session.execute(
                    select(TelegramMessage).where(TelegramMessage.source_id == source_id)
                )
            )
            .scalars()
            .all()
        )
        return result, leads, messages

    process_result, leads, messages = await run_write(_process_to_lead)
    assert process_result is not None
    assert leads
    assert messages
    assert leads[0].canonical_message_id == messages[0].id
    assert leads[0].band in {"hot", "warm", "cold"}
