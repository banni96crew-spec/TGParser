"""Integration — Wave 02 canonical identity + durable suppress (SRC-033..036, STO-017).

Covers: provisional→peer merge, retention immunity, restart restore from DB,
same source / two providers → one suppress identity.
Temp SQLite only; no live DB / secrets.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from telegram_lead_discovery.collector.fake import FakeTelegramGateway, make_hit, make_source
from telegram_lead_discovery.infrastructure.maintenance import run_daily_purge
from telegram_lead_discovery.infrastructure.paths import (
    database_path,
    ensure_app_directories,
    ensure_directories,
    resolve_app_paths,
)
from telegram_lead_discovery.source_discovery.keyword_run import start_keyword_discovery_run
from telegram_lead_discovery.source_discovery.profile_service import (
    create_keyword_discovery_profile,
)
from telegram_lead_discovery.source_discovery.promotion import dismiss_opportunity
from telegram_lead_discovery.source_discovery.worker import (
    _load_dismissed_sources,
    claim_and_process_keyword_job,
)
from telegram_lead_discovery.storage.db import dispose_engine, init_engine, session_scope
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import (
    DiscoveryRun,
    DismissedKeywordSource,
    SourceDiscoveryEvidence,
    SourceOpportunitySnapshot,
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


def _fresh(hours: int = 2) -> datetime:
    return datetime.now(UTC) - timedelta(hours=hours)


@pytest.mark.asyncio
async def test_unresolved_username_merges_into_resolved_peer_src034(db_env) -> None:
    """AT-SRC-034: provisional username suppress merges into peer:<id> with provenance."""
    from telegram_lead_discovery.source_discovery.canonical_identity import (
        CanonicalSourceIdentity,
        merge_provisional_into_peer,
        provisional_username_key,
    )
    from telegram_lead_discovery.source_discovery.promotion import (
        upsert_dismiss_suppress_for_identity,
    )

    provisional_key = provisional_username_key("PendingChat")
    assert provisional_key == "username:pendingchat"

    async with session_scope() as session:
        provisional = CanonicalSourceIdentity(
            canonical_key=provisional_key,
            telegram_id=None,
            username_normalized="pendingchat",
        )
        row = await upsert_dismiss_suppress_for_identity(
            session,
            identity=provisional,
            reason="dismissed_before_resolve",
            operator_trigger="DismissOpportunity",
        )
        assert row.canonical_key == provisional_key
        assert getattr(row, "telegram_id", None) is None or getattr(
            row, "source_telegram_id", None
        ) in (None, 0)

        merged = await merge_provisional_into_peer(
            session,
            provisional_key=provisional_key,
            peer_telegram_id=910_001,
            aliases=("pendingchat",),
        )
        assert merged.canonical_key == "peer:910001"
        assert merged.telegram_id == 910_001

    async with session_scope() as session:
        rows = list((await session.execute(select(DismissedKeywordSource))).scalars().all())
        assert len(rows) == 1
        assert rows[0].canonical_key == "peer:910001"
        # Dismiss provenance retained across merge.
        assert rows[0].dismiss_reason == "dismissed_before_resolve"
        aliases = json.loads(rows[0].aliases_json or "[]")
        assert "pendingchat" in aliases or rows[0].username_normalized == "pendingchat"


@pytest.mark.asyncio
async def test_retention_does_not_delete_suppress_ledger_sto017(db_env) -> None:
    """AT-STO-017 / AT-SRC-035: purge may delete old snapshots; suppress rows remain."""
    paths = ensure_app_directories(resolve_app_paths())
    now = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    age_91 = now - timedelta(days=91)

    async with session_scope() as session:
        run = DiscoveryRun(
            run_type="keyword_scouting",
            state="succeeded",
            started_at=age_91,
            finished_at=age_91,
            created_at=age_91,
        )
        session.add(run)
        await session.flush()
        snap = SourceOpportunitySnapshot(
            run_id=run.id,
            source_telegram_id=600_001,
            username="purge_peer",
            title="Purge Peer",
            source_type="channel",
            score=20,
            band="weak",
            review_state="dismissed",
            dismiss_reason="old_noise",
            sample_timestamps="[]",
            score_components_json="{}",
            discovery_channels_json="[]",
            created_at=age_91,
            updated_at=age_91,
        )
        session.add(snap)
        await session.flush()
        await dismiss_opportunity(
            session,
            opportunity_id=snap.id,
            version=snap.version,
            reason="old_noise",
        )

    async with session_scope() as session:
        before = (
            await session.execute(select(func.count()).select_from(DismissedKeywordSource))
        ).scalar_one()
        assert before >= 1
        await run_daily_purge(session, paths=paths, now=now)

    async with session_scope() as session:
        after = (
            await session.execute(select(func.count()).select_from(DismissedKeywordSource))
        ).scalar_one()
        assert after == before
        assert after >= 1


@pytest.mark.asyncio
async def test_run_restart_restores_suppress_from_db(db_env) -> None:
    """Retry/restart MUST reload suppress membership from DB, not process memory."""
    async with session_scope() as session:
        run = DiscoveryRun(
            run_type="keyword_scouting",
            state="succeeded",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
        session.add(run)
        await session.flush()
        snap = SourceOpportunitySnapshot(
            run_id=run.id,
            source_telegram_id=610_001,
            username="restart_peer",
            title="Restart Peer",
            source_type="megagroup",
            score=40,
            band="weak",
            review_state="unreviewed",
            sample_timestamps="[]",
            score_components_json="{}",
            discovery_channels_json='["global_message"]',
        )
        session.add(snap)
        await session.flush()
        await dismiss_opportunity(
            session,
            opportunity_id=snap.id,
            version=snap.version,
            reason="hide",
        )

    # Simulate process restart: new session loads suppress index from SQLite.
    async with session_scope() as session:
        index = await _load_dismissed_sources(session)
        assert 610_001 in index.by_telegram_id
        assert "restart_peer" in index.by_username
        match_tid = index.by_telegram_id[610_001]
        assert match_tid.telegram_id == 610_001


@pytest.mark.asyncio
async def test_same_source_two_providers_one_suppress_identity(db_env) -> None:
    """Exact same peer from two providers → one identity / one suppress membership."""
    gw = FakeTelegramGateway()
    peer = make_source(
        telegram_id=620_001,
        username="dual_provider",
        source_type="megagroup",
        title="Dual",
    )
    other = make_source(
        telegram_id=620_099,
        username="other_ok",
        source_type="megagroup",
        title="Other",
    )
    gw.register_source("dual_provider", peer)
    gw.register_source("other_ok", other)
    gw.set_directory_results([peer, other])
    gw.set_quota(free_slot_available=True)
    gw.set_public_post_hits("нужен сайт", [])
    gw.set_global_hits(
        [
            make_hit(
                source=peer,
                message_id=1,
                excerpt="нужен сайт dual",
                published_at=_fresh(),
            ),
            make_hit(
                source=other,
                message_id=2,
                excerpt="нужен сайт other",
                published_at=_fresh(1),
            ),
        ]
    )

    async with session_scope() as session:
        profile = await create_keyword_discovery_profile(
            session,
            name="dual-provider",
            post_queries=["нужен сайт"],
            directory_queries=["ecommerce"],
            source_scope="groups",
        )
        profile_id = profile.profile.id
        started = await start_keyword_discovery_run(session, profile_id=profile_id)
        run1_id = started.run.id

    async with session_scope() as session:
        outcome = await claim_and_process_keyword_job(session, gw)
        assert outcome is not None

    async with session_scope() as session:
        snaps = list(
            (
                await session.execute(
                    select(SourceOpportunitySnapshot).where(
                        SourceOpportunitySnapshot.run_id == run1_id,
                        SourceOpportunitySnapshot.source_telegram_id == 620_001,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(snaps) == 1
        await dismiss_opportunity(
            session,
            opportunity_id=snaps[0].id,
            version=snaps[0].version,
            reason="duplicate_providers",
        )

    async with session_scope() as session:
        suppress_rows = list(
            (await session.execute(select(DismissedKeywordSource))).scalars().all()
        )
        assert len(suppress_rows) == 1
        assert suppress_rows[0].source_telegram_id == 620_001
        canonical_key = getattr(suppress_rows[0], "canonical_key", None)
        assert canonical_key == "peer:620001"

    # Second run: both providers resurface the dismissed peer — still suppressed once.
    async with session_scope() as session:
        started = await start_keyword_discovery_run(session, profile_id=profile_id)
        run2_id = started.run.id

    gw.set_global_hits(
        [
            make_hit(
                source=peer,
                message_id=11,
                excerpt="нужен сайт dual again",
                published_at=_fresh(),
            ),
            make_hit(
                source=other,
                message_id=12,
                excerpt="нужен сайт other again",
                published_at=_fresh(1),
            ),
        ]
    )
    async with session_scope() as session:
        outcome = await claim_and_process_keyword_job(session, gw)
        assert outcome is not None

    async with session_scope() as session:
        evidence_ids = set(
            (
                await session.execute(
                    select(SourceDiscoveryEvidence.source_telegram_id).where(
                        SourceDiscoveryEvidence.run_id == run2_id
                    )
                )
            )
            .scalars()
            .all()
        )
        opp_ids = set(
            (
                await session.execute(
                    select(SourceOpportunitySnapshot.source_telegram_id).where(
                        SourceOpportunitySnapshot.run_id == run2_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert 620_001 not in evidence_ids
        assert 620_001 not in opp_ids
        run = await session.get(DiscoveryRun, run2_id)
        assert run is not None
        counters = json.loads(run.counters_json or "{}")
        assert int(counters.get("dismissed_suppressed", 0)) >= 1
        # Still a single suppress membership after multi-provider recurrence.
        assert (
            await session.execute(select(func.count()).select_from(DismissedKeywordSource))
        ).scalar_one() == 1
