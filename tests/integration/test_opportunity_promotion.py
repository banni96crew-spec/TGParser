"""Integration — PromoteOpportunityToCandidate / DismissOpportunity (AT-SRC-026/027)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from telegram_lead_discovery.infrastructure.paths import database_path, ensure_directories
from telegram_lead_discovery.source_discovery.promotion import (
    DEFAULT_CANDIDATE_QUALITY_SCORE,
    OpportunityReviewStateError,
    OpportunityVersionConflict,
    dismiss_opportunity,
    promote_opportunity_to_candidate,
)
from telegram_lead_discovery.storage.db import dispose_engine, init_engine, session_scope
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import (
    CollectorCheckpoint,
    DiscoveryRun,
    DismissedKeywordSource,
    Job,
    SourceAlias,
    SourceApprovalEvent,
    SourceDiscoveryEvent,
    SourceOpportunitySnapshot,
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


async def _insert_run(session) -> DiscoveryRun:
    run = DiscoveryRun(
        run_type="keyword",
        state="succeeded",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    session.add(run)
    await session.flush()
    return run


async def _insert_snapshot(
    session,
    *,
    run_id: int,
    telegram_id: int = 900_001,
    username: str | None = "scout_channel",
    title: str = "Scout Channel",
    source_type: str = "channel",
    score: int = 88,
    linked_parent_telegram_id: int | None = None,
    review_state: str = "unreviewed",
    version: int = 1,
) -> SourceOpportunitySnapshot:
    snap = SourceOpportunitySnapshot(
        run_id=run_id,
        source_telegram_id=telegram_id,
        username=username,
        title=title,
        source_type=source_type,
        public_url=f"https://t.me/{username}" if username else None,
        linked_parent_telegram_id=linked_parent_telegram_id,
        qualified_count=5,
        excluded_count=1,
        active_week_count=3,
        ecommerce_qualified_count=2,
        sample_message_count=5,
        sample_timestamps="[]",
        score=score,
        band="promising",
        score_components_json="{}",
        discovery_channels_json='["global_message"]',
        review_state=review_state,
        version=version,
    )
    session.add(snap)
    await session.flush()
    return snap


@pytest.mark.asyncio
async def test_at_src_026_promote_creates_candidate(db_env) -> None:
    async with session_scope() as session:
        run = await _insert_run(session)
        snap = await _insert_snapshot(session, run_id=run.id, score=88)
        opportunity_id = snap.id
        version = snap.version

    async with session_scope() as session:
        result = await promote_opportunity_to_candidate(
            session, opportunity_id=opportunity_id, version=version
        )
        assert result.created_new is True
        assert result.idempotent is False
        assert result.method == "keyword_search"
        assert result.source.lifecycle_state == "candidate"
        assert result.source.telegram_id == 900_001
        assert result.source.username_normalized == "scout_channel"
        assert result.source.quality_score == DEFAULT_CANDIDATE_QUALITY_SCORE
        assert result.source.quality_score != 88
        assert result.snapshot.review_state == "promoted"
        assert result.snapshot.promoted_source_id == result.source.id
        assert result.snapshot.version == version + 1
        source_id = result.source.id

    async with session_scope() as session:
        sources = list((await session.execute(select(TelegramSource))).scalars().all())
        assert len(sources) == 1
        events = list(
            (
                await session.execute(
                    select(SourceDiscoveryEvent).where(SourceDiscoveryEvent.source_id == source_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1
        assert events[0].method == "keyword_search"
        assert events[0].outcome == "created"

        checkpoints = (
            await session.execute(select(func.count()).select_from(CollectorCheckpoint))
        ).scalar_one()
        assert checkpoints == 0
        jobs = (await session.execute(select(func.count()).select_from(Job))).scalar_one()
        assert jobs == 0
        approvals = (
            await session.execute(select(func.count()).select_from(SourceApprovalEvent))
        ).scalar_one()
        assert approvals == 0
        monitoring = list(
            (
                await session.execute(
                    select(TelegramSource).where(TelegramSource.lifecycle_state == "monitoring")
                )
            )
            .scalars()
            .all()
        )
        assert monitoring == []


@pytest.mark.asyncio
async def test_at_src_027_promote_idempotent_no_duplicate(db_env) -> None:
    async with session_scope() as session:
        run = await _insert_run(session)
        snap = await _insert_snapshot(session, run_id=run.id)
        opportunity_id = snap.id
        version = snap.version

    async with session_scope() as session:
        first = await promote_opportunity_to_candidate(
            session, opportunity_id=opportunity_id, version=version
        )
        source_id = first.source.id
        new_version = first.snapshot.version

    async with session_scope() as session:
        second = await promote_opportunity_to_candidate(
            session, opportunity_id=opportunity_id, version=new_version
        )
        assert second.idempotent is True
        assert second.created_new is False
        assert second.source.id == source_id
        assert second.snapshot.review_state == "promoted"
        assert second.snapshot.version == new_version

    async with session_scope() as session:
        source_count = (
            await session.execute(select(func.count()).select_from(TelegramSource))
        ).scalar_one()
        assert source_count == 1
        event_count = (
            await session.execute(select(func.count()).select_from(SourceDiscoveryEvent))
        ).scalar_one()
        assert event_count == 1

    async with session_scope() as session:
        with pytest.raises(OpportunityVersionConflict):
            await promote_opportunity_to_candidate(
                session, opportunity_id=opportunity_id, version=version
            )


@pytest.mark.asyncio
async def test_at_src_026_promote_links_existing_without_duplicate(db_env) -> None:
    async with session_scope() as session:
        existing = TelegramSource(
            telegram_id=900_002,
            username_normalized="existing_src",
            title="Existing",
            source_type="channel",
            public_url="https://t.me/existing_src",
            lifecycle_state="candidate",
            quality_score=3,
        )
        session.add(existing)
        await session.flush()
        existing_id = existing.id

        run = await _insert_run(session)
        snap = await _insert_snapshot(
            session,
            run_id=run.id,
            telegram_id=900_002,
            username="existing_src",
            score=70,
        )
        opportunity_id = snap.id
        version = snap.version

    async with session_scope() as session:
        result = await promote_opportunity_to_candidate(
            session, opportunity_id=opportunity_id, version=version
        )
        assert result.created_new is False
        assert result.source.id == existing_id
        assert result.source.lifecycle_state == "candidate"
        assert result.source.quality_score == 3
        assert result.snapshot.promoted_source_id == existing_id

    async with session_scope() as session:
        source_count = (
            await session.execute(select(func.count()).select_from(TelegramSource))
        ).scalar_one()
        assert source_count == 1
        events = list((await session.execute(select(SourceDiscoveryEvent))).scalars().all())
        assert len(events) == 1
        assert events[0].outcome == "merged"
        assert events[0].method == "keyword_search"


@pytest.mark.asyncio
async def test_promote_links_via_alias(db_env) -> None:
    async with session_scope() as session:
        existing = TelegramSource(
            telegram_id=900_010,
            username_normalized="current_name",
            title="Aliased",
            source_type="megagroup",
            lifecycle_state="approved",
            quality_score=2,
        )
        session.add(existing)
        await session.flush()
        session.add(
            SourceAlias(
                source_id=existing.id,
                normalized_username="old_alias",
            )
        )
        run = await _insert_run(session)
        # telegram_id unknown in registry; match via SourceAlias username (SRC-022).
        snap = await _insert_snapshot(
            session,
            run_id=run.id,
            telegram_id=900_099,
            username="old_alias",
            source_type="megagroup",
        )
        opportunity_id = snap.id
        version = snap.version
        existing_id = existing.id

    async with session_scope() as session:
        result = await promote_opportunity_to_candidate(
            session, opportunity_id=opportunity_id, version=version
        )
        assert result.created_new is False
        assert result.source.id == existing_id
        assert result.source.lifecycle_state == "approved"

    async with session_scope() as session:
        assert (
            await session.execute(select(func.count()).select_from(TelegramSource))
        ).scalar_one() == 1


@pytest.mark.asyncio
async def test_promote_linked_discussion_method(db_env) -> None:
    async with session_scope() as session:
        run = await _insert_run(session)
        snap = await _insert_snapshot(
            session,
            run_id=run.id,
            telegram_id=900_050,
            username="flood_group",
            source_type="megagroup",
            linked_parent_telegram_id=900_001,
        )
        opportunity_id = snap.id
        version = snap.version

    async with session_scope() as session:
        result = await promote_opportunity_to_candidate(
            session, opportunity_id=opportunity_id, version=version
        )
        assert result.method == "linked_discussion"

    async with session_scope() as session:
        event = (await session.execute(select(SourceDiscoveryEvent))).scalar_one()
        assert event.method == "linked_discussion"


@pytest.mark.asyncio
async def test_dismiss_does_not_create_source(db_env) -> None:
    async with session_scope() as session:
        run = await _insert_run(session)
        snap = await _insert_snapshot(session, run_id=run.id, telegram_id=900_077)
        opportunity_id = snap.id
        version = snap.version

    async with session_scope() as session:
        dismissed = await dismiss_opportunity(
            session,
            opportunity_id=opportunity_id,
            version=version,
            reason="not_relevant",
        )
        assert dismissed.review_state == "dismissed"
        assert dismissed.dismiss_reason == "not_relevant"
        assert dismissed.promoted_source_id is None
        assert dismissed.version == version + 1
        new_version = dismissed.version

    async with session_scope() as session:
        assert (
            await session.execute(select(func.count()).select_from(TelegramSource))
        ).scalar_one() == 0
        dismissed_rows = (
            await session.execute(select(DismissedKeywordSource))
        ).scalars().all()
        assert len(dismissed_rows) == 1
        assert dismissed_rows[0].source_telegram_id == 900_077
        assert dismissed_rows[0].username_normalized == "scout_channel"
        assert dismissed_rows[0].dismiss_reason == "not_relevant"
        assert (
            await session.execute(select(func.count()).select_from(SourceDiscoveryEvent))
        ).scalar_one() == 0

        again = await dismiss_opportunity(
            session,
            opportunity_id=opportunity_id,
            version=new_version,
            reason="ignored",
        )
        assert again.review_state == "dismissed"
        assert again.dismiss_reason == "not_relevant"
        assert (
            await session.execute(select(func.count()).select_from(DismissedKeywordSource))
        ).scalar_one() == 1

        with pytest.raises(OpportunityReviewStateError, match="opportunity_dismissed"):
            await promote_opportunity_to_candidate(
                session, opportunity_id=opportunity_id, version=new_version
            )
