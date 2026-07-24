"""Retention purge — exports/tmp, terminal outbox, keyword discovery artifacts (STO-016)."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from telegram_lead_discovery.infrastructure.maintenance import run_daily_purge
from telegram_lead_discovery.infrastructure.paths import ensure_app_directories, resolve_app_paths
from telegram_lead_discovery.settings.service import seed_defaults
from telegram_lead_discovery.storage.db import dispose_engine, init_engine
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import (
    DiscoveryRun,
    DiscoveryRunQuery,
    KeywordDiscoveryProfile,
    KeywordDiscoveryProfileVersion,
    NotificationDelivery,
    NotificationOutbox,
    SourceDiscoveryEvidence,
    SourceOpportunitySnapshot,
    TelegramSource,
)
from telegram_lead_discovery.storage.retention import (
    BATCH_LIMIT,
    EVIDENCE_RETENTION_UI_MESSAGE,
    purge_exports_and_tmp,
)
from telegram_lead_discovery.storage.session import configure_session_factory, run_write


@pytest.fixture
async def purge_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    paths = ensure_app_directories(resolve_app_paths())
    upgrade_head(paths.database_path)
    engine = await init_engine(paths.database_path)
    configure_session_factory(engine)

    async def _seed(session):
        await seed_defaults(session)

    await run_write(_seed)
    yield paths
    await dispose_engine()


@pytest.mark.asyncio
async def test_purge_deletes_old_export_files(purge_env) -> None:
    paths = purge_env
    stale = paths.exports_dir / "stale.csv"
    stale.write_text("a,b\n", encoding="utf-8")
    old = time.time() - 7200
    os.utime(stale, (old, old))
    fresh = paths.tmp_dir / "fresh.tmp"
    fresh.write_text("ok", encoding="utf-8")

    deleted = purge_exports_and_tmp(paths, now=datetime.now(UTC))
    assert deleted >= 1
    assert not stale.exists()
    assert fresh.exists()


@pytest.mark.asyncio
async def test_daily_purge_removes_terminal_outbox(purge_env) -> None:
    paths = purge_env
    old = datetime.now(UTC) - timedelta(days=40)

    async def _seed(session):
        row = NotificationOutbox(
            event_type="hot_lead",
            lead_id=None,
            incident_id="inc-1",
            score_version=None,
            idempotency_key="hot_lead:old:1",
            state="sent",
            created_at=old,
        )
        session.add(row)
        await session.flush()
        session.add(
            NotificationDelivery(
                outbox_id=row.id,
                attempt_no=1,
                status="sent",
                attempted_at=old,
            )
        )
        return row.id

    await run_write(_seed)

    async def _purge(session):
        return await run_daily_purge(session, paths=paths, now=datetime.now(UTC))

    result = await run_write(_purge)
    assert result.terminal_outbox_deleted >= 1


@pytest.mark.asyncio
async def test_keyword_retention_matrix_31_and_91_days(purge_env) -> None:
    """AT-STO-016 / AT-SRC-030 — excerpt 30d; rows/snapshots/queries/runs 90d; profiles kept."""
    paths = purge_env
    now = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)
    age_31 = now - timedelta(days=31)
    age_91 = now - timedelta(days=91)
    age_10 = now - timedelta(days=10)

    async def _seed(session):
        profile = KeywordDiscoveryProfile(name="retain-profile", state="active", current_version=1)
        session.add(profile)
        await session.flush()
        version = KeywordDiscoveryProfileVersion(
            profile_id=profile.id,
            version=1,
            post_queries_json='["a"]',
            directory_queries_json="[]",
            required_service_profiles_json="[]",
            additional_exclusions_json="[]",
            source_scope="all",
            created_at=age_91,
        )
        session.add(version)
        await session.flush()

        source = TelegramSource(
            telegram_id=5_500_001,
            username_normalized="promoted_src",
            title="Promoted",
            source_type="channel",
            lifecycle_state="candidate",
            quality_score=50,
        )
        session.add(source)
        await session.flush()

        run_old = DiscoveryRun(
            run_type="keyword_scouting",
            profile_version_id=version.id,
            state="succeeded",
            started_at=age_91,
            finished_at=age_91,
            created_at=age_91,
        )
        run_mid = DiscoveryRun(
            run_type="keyword_scouting",
            profile_version_id=version.id,
            state="partial",
            started_at=age_31,
            finished_at=age_31,
            created_at=age_31,
        )
        run_fresh = DiscoveryRun(
            run_type="keyword_scouting",
            profile_version_id=version.id,
            state="succeeded",
            started_at=age_10,
            finished_at=age_10,
            created_at=age_10,
        )
        run_promoted = DiscoveryRun(
            run_type="keyword_scouting",
            profile_version_id=version.id,
            state="succeeded",
            started_at=age_91,
            finished_at=age_91,
            created_at=age_91,
        )
        session.add_all([run_old, run_mid, run_fresh, run_promoted])
        await session.flush()

        session.add_all(
            [
                DiscoveryRunQuery(
                    run_id=run_old.id,
                    ordinal=1,
                    query_kind="global_message",
                    query_text="old",
                    state="succeeded",
                    finished_at=age_91,
                ),
                DiscoveryRunQuery(
                    run_id=run_mid.id,
                    ordinal=1,
                    query_kind="global_message",
                    query_text="mid",
                    state="succeeded",
                    finished_at=age_31,
                ),
                DiscoveryRunQuery(
                    run_id=run_fresh.id,
                    ordinal=1,
                    query_kind="global_message",
                    query_text="fresh",
                    state="succeeded",
                    finished_at=age_10,
                ),
            ]
        )

        session.add_all(
            [
                SourceDiscoveryEvidence(
                    run_id=run_old.id,
                    source_telegram_id=1001,
                    source_title="old-ev",
                    source_type="megagroup",
                    telegram_message_id=1,
                    published_at=age_91,
                    excerpt="secret excerpt old",
                    normalized_hash="h-old",
                    created_at=age_91,
                ),
                SourceDiscoveryEvidence(
                    run_id=run_mid.id,
                    source_telegram_id=1002,
                    source_title="mid-ev",
                    source_type="megagroup",
                    telegram_message_id=2,
                    published_at=age_31,
                    excerpt="secret excerpt mid",
                    normalized_hash="h-mid",
                    created_at=age_31,
                ),
                SourceDiscoveryEvidence(
                    run_id=run_fresh.id,
                    source_telegram_id=1003,
                    source_title="fresh-ev",
                    source_type="megagroup",
                    telegram_message_id=3,
                    published_at=age_10,
                    excerpt="secret excerpt fresh",
                    normalized_hash="h-fresh",
                    created_at=age_10,
                ),
            ]
        )

        session.add_all(
            [
                SourceOpportunitySnapshot(
                    run_id=run_old.id,
                    source_telegram_id=2001,
                    title="unpromoted-old",
                    source_type="megagroup",
                    score=40,
                    band="weak",
                    review_state="unreviewed",
                    created_at=age_91,
                    updated_at=age_91,
                ),
                SourceOpportunitySnapshot(
                    run_id=run_mid.id,
                    source_telegram_id=2002,
                    title="unpromoted-mid",
                    source_type="megagroup",
                    score=40,
                    band="weak",
                    review_state="dismissed",
                    created_at=age_31,
                    updated_at=age_31,
                ),
                SourceOpportunitySnapshot(
                    run_id=run_promoted.id,
                    source_telegram_id=source.telegram_id,
                    source_id=source.id,
                    title="promoted-old",
                    source_type="channel",
                    score=90,
                    band="promising",
                    review_state="promoted",
                    promoted_source_id=source.id,
                    created_at=age_91,
                    updated_at=age_91,
                ),
            ]
        )
        return {
            "profile_id": profile.id,
            "version_id": version.id,
            "run_old_id": run_old.id,
            "run_mid_id": run_mid.id,
            "run_fresh_id": run_fresh.id,
            "run_promoted_id": run_promoted.id,
        }

    ids = await run_write(_seed)

    async def _purge(session):
        return await run_daily_purge(session, paths=paths, now=now)

    result = await run_write(_purge)
    assert result.evidence_excerpts_cleared >= 2
    assert result.evidence_rows_deleted >= 1
    assert result.unpromoted_snapshots_deleted >= 1
    assert result.keyword_queries_deleted >= 1
    assert result.terminal_keyword_runs_deleted >= 1
    assert EVIDENCE_RETENTION_UI_MESSAGE == "Доказательства очищены по retention policy"
    assert BATCH_LIMIT == 500

    async def _assert(session):
        mid_ev = (
            await session.execute(
                select(SourceDiscoveryEvidence).where(
                    SourceDiscoveryEvidence.run_id == ids["run_mid_id"]
                )
            )
        ).scalar_one()
        assert mid_ev.excerpt == ""

        old_ev_count = (
            await session.execute(
                select(func.count())
                .select_from(SourceDiscoveryEvidence)
                .where(SourceDiscoveryEvidence.run_id == ids["run_old_id"])
            )
        ).scalar_one()
        assert old_ev_count == 0

        fresh_ev = (
            await session.execute(
                select(SourceDiscoveryEvidence).where(
                    SourceDiscoveryEvidence.run_id == ids["run_fresh_id"]
                )
            )
        ).scalar_one()
        assert fresh_ev.excerpt == "secret excerpt fresh"

        old_snap = (
            await session.execute(
                select(func.count())
                .select_from(SourceOpportunitySnapshot)
                .where(SourceOpportunitySnapshot.run_id == ids["run_old_id"])
            )
        ).scalar_one()
        assert old_snap == 0

        mid_snap = (
            await session.execute(
                select(func.count())
                .select_from(SourceOpportunitySnapshot)
                .where(SourceOpportunitySnapshot.run_id == ids["run_mid_id"])
            )
        ).scalar_one()
        assert mid_snap == 1

        promoted_snap = (
            await session.execute(
                select(SourceOpportunitySnapshot).where(
                    SourceOpportunitySnapshot.run_id == ids["run_promoted_id"]
                )
            )
        ).scalar_one()
        assert promoted_snap.promoted_source_id is not None

        old_queries = (
            await session.execute(
                select(func.count())
                .select_from(DiscoveryRunQuery)
                .where(DiscoveryRunQuery.run_id == ids["run_old_id"])
            )
        ).scalar_one()
        assert old_queries == 0

        mid_queries = (
            await session.execute(
                select(func.count())
                .select_from(DiscoveryRunQuery)
                .where(DiscoveryRunQuery.run_id == ids["run_mid_id"])
            )
        ).scalar_one()
        assert mid_queries == 1

        assert (await session.get(DiscoveryRun, ids["run_old_id"])) is None
        assert (await session.get(DiscoveryRun, ids["run_mid_id"])) is not None
        assert (await session.get(DiscoveryRun, ids["run_fresh_id"])) is not None
        assert (await session.get(DiscoveryRun, ids["run_promoted_id"])) is not None

        assert (await session.get(KeywordDiscoveryProfile, ids["profile_id"])) is not None
        assert (
            await session.get(KeywordDiscoveryProfileVersion, ids["version_id"])
        ) is not None

    await run_write(_assert)
