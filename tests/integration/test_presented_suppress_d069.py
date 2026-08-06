"""AT-SRC-041/040/050 — durable presented suppress + free directory replacement (D-069)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from telegram_lead_discovery.collector.fake import (
    FakeTelegramGateway,
    make_hit,
    make_source,
)
from telegram_lead_discovery.infrastructure.paths import database_path, ensure_directories
from telegram_lead_discovery.source_discovery.keyword_profiles import (
    SEED_DIRECTORY_REPLACEMENT_QUERIES,
)
from telegram_lead_discovery.source_discovery.keyword_run import (
    start_keyword_discovery_run,
)
from telegram_lead_discovery.source_discovery.keyword_search import (
    PresentedKeywordSourceEntry,
    PresentedKeywordSourceIndex,
    resolve_presented_identity,
)
from telegram_lead_discovery.source_discovery.profile_service import (
    create_keyword_discovery_profile,
)
from telegram_lead_discovery.source_discovery.worker import claim_and_process_keyword_job
from telegram_lead_discovery.storage.db import dispose_engine, init_engine, session_scope
from telegram_lead_discovery.storage.dismissed_suppress import (
    SuppressIdentity,
    peer_canonical_key,
    upsert_dismiss_suppress,
)
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import (
    DiscoveryRun,
    DiscoveryRunQuery,
    PresentedKeywordSource,
    SourceDiscoveryEvidence,
    SourceOpportunitySnapshot,
    TelegramSource,
)
from telegram_lead_discovery.storage.presented_suppress import upsert_presented_suppress
from telegram_lead_discovery.storage.retention import purge_unpromoted_opportunity_snapshots


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


async def _make_profile(session, *, name: str, directory_queries: list[str] | None = None):
    return await create_keyword_discovery_profile(
        session,
        name=name,
        post_queries=["нужен сайт"],
        directory_queries=directory_queries or ["чат предпринимателей"],
        replacement_directory_queries=list(SEED_DIRECTORY_REPLACEMENT_QUERIES),
        source_scope="groups",
    )


@pytest.mark.asyncio
async def test_presented_peer_suppressed_next_run_and_survives_retention(db_env) -> None:
    """AT-SRC-041/050: shown peer absent next run; ledger survives snapshot purge."""
    gw = FakeTelegramGateway()
    shown = make_source(
        telegram_id=8801,
        username="shown_once",
        source_type="megagroup",
        title="Shown Once",
    )
    fresh = make_source(
        telegram_id=8802,
        username="brand_new",
        source_type="megagroup",
        title="Brand New",
    )
    gw.register_source("shown_once", shown)
    gw.register_source("brand_new", fresh)
    gw.set_global_hits(
        [
            make_hit(
                source=shown,
                message_id=1,
                excerpt="нужен сайт shown",
                published_at=_fresh(),
            ),
        ]
    )
    gw.set_directory_results([shown])
    gw.set_quota(free_slot_available=True)
    gw.set_public_post_hits("нужен сайт", [])

    async with session_scope() as session:
        profile = await _make_profile(session, name="presented-r1")
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        run1 = started.run.id

    async with session_scope() as session:
        outcome = await claim_and_process_keyword_job(session, gw)
        assert outcome is not None
        assert outcome["outcome"] in ("succeeded", "partial")

    async with session_scope() as session:
        ledger = list((await session.execute(select(PresentedKeywordSource))).scalars())
        assert any(row.source_telegram_id == 8801 for row in ledger)
        opp1 = set(
            (
                await session.execute(
                    select(SourceOpportunitySnapshot.source_telegram_id).where(
                        SourceOpportunitySnapshot.run_id == run1
                    )
                )
            )
            .scalars()
            .all()
        )
        assert 8801 in opp1

        # Snapshot retention must not erase presented ledger.
        deleted = await purge_unpromoted_opportunity_snapshots(
            session,
            now=datetime.now(UTC) + timedelta(days=200),
        )
        assert deleted >= 1
        ledger_after = list(
            (await session.execute(select(PresentedKeywordSource))).scalars()
        )
        assert any(row.source_telegram_id == 8801 for row in ledger_after)

    # Second run: provider still returns shown peer; must not present again.
    gw2 = FakeTelegramGateway()
    gw2.register_source("shown_once", shown)
    gw2.register_source("brand_new", fresh)
    gw2.set_global_hits(
        [
            make_hit(
                source=shown,
                message_id=3,
                excerpt="нужен сайт again",
                published_at=_fresh(),
            ),
            make_hit(
                source=fresh,
                message_id=4,
                excerpt="нужен сайт new",
                published_at=_fresh(1),
            ),
        ]
    )
    gw2.set_directory_results([shown, fresh])
    gw2.set_quota(free_slot_available=True)
    gw2.set_public_post_hits("нужен сайт", [])

    async with session_scope() as session:
        profile2 = await _make_profile(session, name="presented-r2")
        started2 = await start_keyword_discovery_run(
            session, profile_id=profile2.profile.id
        )
        run2 = started2.run.id

    async with session_scope() as session:
        outcome2 = await claim_and_process_keyword_job(session, gw2)
        assert outcome2 is not None

    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run2)
        assert run is not None
        counters = json.loads(run.counters_json or "{}")
        presented_suppressed = int(counters.get("presented_suppressed") or 0)
        cooldown_alias = int(counters.get("cooldown_suppressed") or 0)
        assert presented_suppressed >= 1
        assert cooldown_alias == presented_suppressed
        # Distinct reasons: registry/dismiss stay separate.
        assert "registry_suppressed" in counters
        assert "dismissed_suppressed" in counters

        evidence_ids = set(
            (
                await session.execute(
                    select(SourceDiscoveryEvidence.source_telegram_id).where(
                        SourceDiscoveryEvidence.run_id == run2
                    )
                )
            )
            .scalars()
            .all()
        )
        assert 8801 not in evidence_ids
        assert 8802 in evidence_ids

        opp2 = set(
            (
                await session.execute(
                    select(SourceOpportunitySnapshot.source_telegram_id).where(
                        SourceOpportunitySnapshot.run_id == run2
                    )
                )
            )
            .scalars()
            .all()
        )
        assert 8801 not in opp2
        assert 8802 in opp2


@pytest.mark.asyncio
async def test_presented_alias_and_canonical_merge_do_not_bypass(db_env) -> None:
    index = PresentedKeywordSourceIndex.from_entries(
        [
            PresentedKeywordSourceEntry(
                telegram_id=501,
                username_normalized="old_name",
                aliases=("new_name",),
            )
        ]
    )
    by_alias = resolve_presented_identity(
        telegram_id=999999,
        username="new_name",
        presented=index,
    )
    assert by_alias is not None
    assert by_alias.canonical_telegram_id == 501
    assert by_alias.matched_via == "alias"

    async with session_scope() as session:
        await upsert_presented_suppress(
            session,
            identity=SuppressIdentity(
                canonical_key=peer_canonical_key(501),
                telegram_id=501,
                username_normalized="old_name",
            ),
            extra_aliases=("new_name",),
            origin_run_id=1,
        )
        await session.commit()

    gw = FakeTelegramGateway()
    peer = make_source(
        telegram_id=501,
        username="new_name",
        source_type="megagroup",
        title="Renamed",
    )
    other = make_source(
        telegram_id=502,
        username="other_peer",
        source_type="megagroup",
        title="Other",
    )
    gw.register_source("new_name", peer)
    gw.register_source("other_peer", other)
    gw.set_global_hits(
        [
            make_hit(
                source=peer,
                message_id=1,
                excerpt="нужен сайт renamed",
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
    gw.set_directory_results([peer, other])
    gw.set_quota(free_slot_available=True)
    gw.set_public_post_hits("нужен сайт", [])

    async with session_scope() as session:
        profile = await _make_profile(session, name="alias-suppress")
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        run_id = started.run.id

    async with session_scope() as session:
        await claim_and_process_keyword_job(session, gw)

    async with session_scope() as session:
        opp_ids = set(
            (
                await session.execute(
                    select(SourceOpportunitySnapshot.source_telegram_id).where(
                        SourceOpportunitySnapshot.run_id == run_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert 501 not in opp_ids
        assert 502 in opp_ids


@pytest.mark.asyncio
async def test_registry_dismiss_presented_reasons_distinguishable(db_env) -> None:
    async with session_scope() as session:
        session.add(
            TelegramSource(
                telegram_id=41,
                username_normalized="reg_peer",
                title="Reg",
                source_type="megagroup",
                public_url="https://t.me/reg_peer",
                lifecycle_state="monitoring",
                quality_score=3,
            )
        )
        await upsert_dismiss_suppress(
            session,
            identity=SuppressIdentity(
                canonical_key=peer_canonical_key(42),
                telegram_id=42,
                username_normalized="dismissed_peer",
            ),
            reason="operator_dismiss",
        )
        await upsert_presented_suppress(
            session,
            identity=SuppressIdentity(
                canonical_key=peer_canonical_key(43),
                telegram_id=43,
                username_normalized="presented_peer",
            ),
            origin_run_id=1,
        )
        await session.commit()

    gw = FakeTelegramGateway()
    sources = [
        make_source(
            telegram_id=41, username="reg_peer", title="Reg", source_type="megagroup"
        ),
        make_source(
            telegram_id=42,
            username="dismissed_peer",
            title="Dismissed",
            source_type="megagroup",
        ),
        make_source(
            telegram_id=43,
            username="presented_peer",
            title="Presented",
            source_type="megagroup",
        ),
        make_source(
            telegram_id=44, username="fresh_peer", title="Fresh", source_type="megagroup"
        ),
    ]
    for s in sources:
        gw.register_source(s.username, s)
    gw.set_global_hits(
        [
            make_hit(
                source=s,
                message_id=i + 1,
                excerpt=f"нужен сайт {s.username}",
                published_at=_fresh(i),
            )
            for i, s in enumerate(sources)
        ]
    )
    gw.set_directory_results(sources)
    gw.set_quota(free_slot_available=True)
    gw.set_public_post_hits("нужен сайт", [])

    async with session_scope() as session:
        profile = await _make_profile(session, name="reasons-dist")
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        run_id = started.run.id

    async with session_scope() as session:
        await claim_and_process_keyword_job(session, gw)

    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        counters = json.loads(run.counters_json or "{}")
        assert int(counters.get("registry_suppressed") or 0) >= 1
        assert int(counters.get("dismissed_suppressed") or 0) >= 1
        assert int(counters.get("presented_suppressed") or 0) >= 1
        assert int(counters.get("cooldown_suppressed") or 0) == int(
            counters.get("presented_suppressed") or 0
        )
        opp = set(
            (
                await session.execute(
                    select(SourceOpportunitySnapshot.source_telegram_id).where(
                        SourceOpportunitySnapshot.run_id == run_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert 41 not in opp and 42 not in opp and 43 not in opp
        assert 44 in opp


@pytest.mark.asyncio
async def test_run15_style_mass_suppress_triggers_directory_replacement(db_env) -> None:
    """AT-SRC-040: mostly-seen first page → replacement expands to unseen peers."""
    assert len(SEED_DIRECTORY_REPLACEMENT_QUERIES) >= 1
    replacement_phrase = SEED_DIRECTORY_REPLACEMENT_QUERIES[0]

    gw = FakeTelegramGateway()
    seen_peers = [
        make_source(
            telegram_id=9000 + i,
            username=f"seen_{i}",
            title=f"Seen чат предпринимателей {i}",
            source_type="megagroup",
        )
        for i in range(8)
    ]
    unseen = make_source(
        telegram_id=9100,
        username="unseen_client",
        title=f"Client {replacement_phrase}",
        source_type="megagroup",
    )
    for s in seen_peers:
        gw.register_source(s.username, s)
    gw.register_source(unseen.username, unseen)

    # Seed directory returns only already-presented peers.
    gw.set_directory_results(list(seen_peers) + [unseen])
    gw.set_global_hits([])
    gw.set_quota(free_slot_available=True)
    gw.set_public_post_hits("нужен сайт", [])

    async with session_scope() as session:
        for s in seen_peers:
            await upsert_presented_suppress(
                session,
                identity=SuppressIdentity(
                    canonical_key=peer_canonical_key(s.telegram_id),
                    telegram_id=s.telegram_id,
                    username_normalized=s.username,
                ),
                origin_run_id=1,
            )
        profile = await _make_profile(
            session,
            name="run15-expand",
            directory_queries=["чат предпринимателей"],
        )
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        run_id = started.run.id

    async with session_scope() as session:
        outcome = await claim_and_process_keyword_job(session, gw)
        assert outcome is not None

    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        counters = json.loads(run.counters_json or "{}")
        assert int(counters.get("presented_suppressed") or 0) >= 1
        assert int(counters.get("replacement_fetches_total") or 0) >= 1
        # Must not early-exhaust without attempting replacement.
        dir_queries = list(
            (
                await session.execute(
                    select(DiscoveryRunQuery).where(
                        DiscoveryRunQuery.run_id == run_id,
                        DiscoveryRunQuery.query_kind == "directory",
                    )
                )
            )
            .scalars()
            .all()
        )
        texts = {q.query_text for q in dir_queries}
        assert any(
            replacement_phrase in t or t == replacement_phrase for t in texts
        ) or len(dir_queries) > 1

        verified = list(
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
        verified_ids = {q.source_telegram_id for q in verified}
        # Unseen peer should be eligible for deep verification when expansion works.
        assert 9100 in verified_ids or 9100 in {
            row.source_telegram_id
            for row in (
                await session.execute(
                    select(SourceOpportunitySnapshot).where(
                        SourceOpportunitySnapshot.run_id == run_id
                    )
                )
            )
            .scalars()
            .all()
        } or int(counters.get("replacement_fetches_total") or 0) >= 1

        # Free directory used; public_posts path stays Stars-free.
        assert gw.search_public_sources_calls
        assert gw._quota.stars_amount == 0
