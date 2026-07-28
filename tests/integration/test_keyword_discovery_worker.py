"""Integration — keyword discovery worker (SRC-019..029 / AT-SRC-020/021/028/029)."""

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
from telegram_lead_discovery.collector.ports import GatewayTransientError
from telegram_lead_discovery.infrastructure.paths import database_path, ensure_directories
from telegram_lead_discovery.source_discovery.keyword_run import (
    KeywordRunStartError,
    cancel_keyword_discovery_run,
    start_keyword_discovery_run,
)
from telegram_lead_discovery.source_discovery.profile_service import (
    create_keyword_discovery_profile,
)
from telegram_lead_discovery.source_discovery.promotion import dismiss_opportunity
from telegram_lead_discovery.source_discovery.worker import (
    HEARTBEAT_SECONDS,
    LEASE_SECONDS,
    TRANSIENT_RETRY_DELAYS_S,
    claim_and_process_keyword_job,
)
from telegram_lead_discovery.storage.db import dispose_engine, init_engine, session_scope
from telegram_lead_discovery.storage.jobs import LEASE_SECONDS as JOB_LEASE_SECONDS
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import (
    CollectorCheckpoint,
    DiscoveryRun,
    DiscoveryRunQuery,
    Job,
    Lead,
    NotificationOutbox,
    SourceDiscoveryEvidence,
    SourceOpportunitySnapshot,
    TelegramEventEnvelope,
    TelegramMessage,
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


def _fresh(hours: int = 2) -> datetime:
    return datetime.now(UTC) - timedelta(hours=hours)


async def _make_profile(session, *, name: str = "test-kw"):
    return await create_keyword_discovery_profile(
        session,
        name=name,
        post_queries=["нужен сайт"],
        directory_queries=["ecommerce"],
        source_scope="groups",
    )


@pytest.mark.asyncio
async def test_lease_and_heartbeat_constants_match_job_store() -> None:
    assert LEASE_SECONDS == 300
    assert HEARTBEAT_SECONDS == 60
    assert TRANSIENT_RETRY_DELAYS_S == (30, 120, 600)


@pytest.mark.asyncio
async def test_start_run_creates_queries_and_job(db_env) -> None:
    async with session_scope() as session:
        profile = await _make_profile(session)
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        assert started.run.run_type == "keyword_scouting"
        assert started.run.search_mode == "free_only"
        assert started.run.state == "queued"
        assert started.job.job_type == "keyword_discovery"
        # groups-only: 1 global + 1 directory + 1 public_posts
        assert started.query_count == 3

        with pytest.raises(KeywordRunStartError, match="active_keyword_run"):
            await start_keyword_discovery_run(session, profile_id=profile.profile.id)


@pytest.mark.asyncio
async def test_worker_happy_path_persists_evidence_not_pipeline(db_env) -> None:
    gw = FakeTelegramGateway()
    group = make_source(
        telegram_id=101,
        username="dev_chat",
        source_type="megagroup",
        title="Dev Chat",
    )
    channel = make_source(
        telegram_id=202,
        username="shop_news",
        source_type="channel",
        title="Shop News",
    )
    gw.register_source("dev_chat", group)
    gw.register_source("shop_news", channel)
    gw.set_global_hits(
        [
            make_hit(
                source=group,
                message_id=11,
                excerpt="нужен сайт под ключ бюджет 100000",
                published_at=_fresh(),
            )
        ]
    )
    gw.set_directory_results([group, channel])
    gw.set_quota(free_slot_available=True)
    gw.set_public_post_hits(
        "нужен сайт",
        [
            make_hit(
                source=channel,
                message_id=22,
                excerpt="нужен сайт интернет-магазин",
                published_at=_fresh(3),
            )
        ],
    )
    discussion = make_source(
        telegram_id=303,
        username="shop_discuss",
        source_type="megagroup",
        title="Shop Discuss",
    )
    gw.set_linked_discussion(202, discussion)
    gw.set_source_message_hits(
        101,
        [
            make_hit(
                source=group,
                message_id=33,
                excerpt="нужен сайт срочно",
                published_at=_fresh(1),
            )
        ],
    )

    async with session_scope() as session:
        profile = await _make_profile(session)
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        run_id = started.run.id

    async with session_scope() as session:
        outcome = await claim_and_process_keyword_job(session, gw)
        assert outcome is not None
        assert outcome["outcome"] in ("succeeded", "partial")

    async with session_scope() as session:
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
                    select(SourceOpportunitySnapshot).where(
                        SourceOpportunitySnapshot.run_id == run_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert snaps
        linked = [s for s in snaps if s.linked_parent_telegram_id == 202]
        assert linked
        assert linked[0].source_telegram_id == 303

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
        assert (
            await session.execute(select(func.count()).select_from(TelegramEventEnvelope))
        ).scalar_one() == 0


@pytest.mark.asyncio
async def test_flood_wait_parks_job_without_sleep(db_env) -> None:
    gw = FakeTelegramGateway()
    until = datetime.now(UTC) + timedelta(hours=1)
    gw.set_flood_wait(until, "search_global")
    group = make_source(telegram_id=1, username="g1", source_type="megagroup")
    gw.set_global_hits(
        [make_hit(source=group, message_id=1, excerpt="нужен сайт", published_at=_fresh())]
    )

    async with session_scope() as session:
        profile = await _make_profile(session, name="flood-prof")
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        run_id = started.run.id
        job_id = started.job.id

    async with session_scope() as session:
        outcome = await claim_and_process_keyword_job(session, gw)
        assert outcome is not None
        assert outcome["outcome"] == "retry_wait"
        assert "until" in outcome

    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        job = await session.get(Job, job_id)
        assert run is not None and job is not None
        assert run.state == "retry_wait_flood"
        assert job.state == "retry_wait"
        assert job.available_at is not None
        got = job.available_at
        if got.tzinfo is None:
            got = got.replace(tzinfo=UTC)
        assert abs((got - until).total_seconds()) < 1
        query = (
            await session.execute(
                select(DiscoveryRunQuery).where(
                    DiscoveryRunQuery.run_id == run_id,
                    DiscoveryRunQuery.query_kind == "global_message",
                )
            )
        ).scalar_one()
        assert query.state == "retry_wait"
        assert query.available_at is not None


@pytest.mark.asyncio
async def test_flood_wait_resume_from_cursor_idempotent(db_env) -> None:
    gw = FakeTelegramGateway()
    group = make_source(telegram_id=7, username="g7", source_type="megagroup")
    gw.register_source("g7", group)
    hits = [
        make_hit(
            source=group,
            message_id=i,
            excerpt=f"нужен сайт page {i}",
            published_at=_fresh(),
        )
        for i in range(1, 6)
    ]
    gw.set_global_hits(hits)
    gw.set_page_size(2)
    gw.set_directory_results([])
    gw.set_quota(free_slot_available=False, premium_required=True)

    until = datetime.now(UTC) + timedelta(seconds=30)
    gw.set_flood_wait(until, "search_global")

    async with session_scope() as session:
        profile = await _make_profile(session, name="cursor-prof")
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        run_id = started.run.id

    async with session_scope() as session:
        first = await claim_and_process_keyword_job(session, gw)
        assert first is not None
        assert first["outcome"] == "retry_wait"

    gw.clear_flood_wait()
    async with session_scope() as session:
        job = (
            await session.execute(
                select(Job).where(Job.dedupe_key == f"keyword_discovery:run:{run_id}")
            )
        ).scalar_one()
        # Make job claimable immediately.
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        query = (
            await session.execute(
                select(DiscoveryRunQuery).where(
                    DiscoveryRunQuery.run_id == run_id,
                    DiscoveryRunQuery.query_kind == "global_message",
                )
            )
        ).scalar_one()
        query.available_at = datetime.now(UTC) - timedelta(seconds=1)

    async with session_scope() as session:
        second = await claim_and_process_keyword_job(session, gw)
        assert second is not None
        assert second["outcome"] in ("succeeded", "partial")

    async with session_scope() as session:
        evidence_n = (
            await session.execute(
                select(func.count())
                .select_from(SourceDiscoveryEvidence)
                .where(SourceDiscoveryEvidence.run_id == run_id)
            )
        ).scalar_one()
        # Max 2 pages × page_size 2 = 4 unique messages (idempotent if replayed).
        assert evidence_n == 4
        assert evidence_n == len(
            list(
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
        )


@pytest.mark.asyncio
async def test_cancel_between_network_calls(db_env) -> None:
    gw = FakeTelegramGateway()
    group = make_source(telegram_id=9, username="g9", source_type="megagroup")
    gw.set_global_hits(
        [make_hit(source=group, message_id=1, excerpt="нужен сайт", published_at=_fresh())]
    )

    # Cancel is requested before worker starts; checked before first network call.
    async with session_scope() as session:
        profile = await _make_profile(session, name="cancel-prof")
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        cancelled = await cancel_keyword_discovery_run(
            session,
            run_id=started.run.id,
            expected_version=started.run.version,
        )
        assert cancelled.run.state == "cancelling"
        assert cancelled.job is not None
        assert cancelled.job.cancel_requested_at is not None
        run_id = started.run.id

    async with session_scope() as session:
        outcome = await claim_and_process_keyword_job(session, gw)
        assert outcome is not None
        assert outcome["outcome"] == "cancelled"

    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        assert run is not None
        assert run.state == "cancelled"
        # Terminal cancel is idempotent.
        again = await cancel_keyword_discovery_run(
            session, run_id=run_id, expected_version=run.version
        )
        assert again.idempotent is True


@pytest.mark.asyncio
async def test_quota_skipped_yields_partial(db_env) -> None:
    gw = FakeTelegramGateway()
    group = make_source(telegram_id=5, username="g5", source_type="megagroup")
    gw.set_global_hits(
        [make_hit(source=group, message_id=1, excerpt="нужен сайт", published_at=_fresh())]
    )
    gw.set_directory_results([])
    gw.set_quota(free_slot_available=False, stars_amount=100)

    async with session_scope() as session:
        profile = await _make_profile(session, name="quota-prof")
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        run_id = started.run.id

    async with session_scope() as session:
        outcome = await claim_and_process_keyword_job(session, gw)
        assert outcome is not None
        assert outcome["outcome"] == "partial"

    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        assert run is not None
        assert run.state == "partial"
        public_q = (
            await session.execute(
                select(DiscoveryRunQuery).where(
                    DiscoveryRunQuery.run_id == run_id,
                    DiscoveryRunQuery.query_kind == "public_posts",
                )
            )
        ).scalar_one()
        assert public_q.state == "quota_skipped"


@pytest.mark.asyncio
async def test_credentials_missing_blocks_start(db_env) -> None:
    async with session_scope() as session:
        profile = await _make_profile(session, name="cred-prof")
        with pytest.raises(KeywordRunStartError, match="telegram_credentials_missing"):
            await start_keyword_discovery_run(
                session,
                profile_id=profile.profile.id,
                credentials_present=False,
            )


class _TransientOnceGateway(FakeTelegramGateway):
    """Raises GatewayTransientError once on search_global, then succeeds."""

    def __init__(self) -> None:
        super().__init__()
        self._transient_left = 1

    async def search_global(self, request):  # type: ignore[override]
        if self._transient_left > 0:
            self._transient_left -= 1
            raise GatewayTransientError("transient_for_test")
        return await super().search_global(request)


@pytest.mark.asyncio
async def test_transient_retry_schedule_30_120_600(db_env) -> None:
    assert TRANSIENT_RETRY_DELAYS_S == (30, 120, 600)
    gw = _TransientOnceGateway()
    group = make_source(telegram_id=77, username="g77", source_type="megagroup")
    gw.set_global_hits(
        [make_hit(source=group, message_id=1, excerpt="нужен сайт", published_at=_fresh())]
    )
    gw.set_directory_results([])
    gw.set_quota(free_slot_available=False, premium_required=True)

    async with session_scope() as session:
        profile = await _make_profile(session, name="transient-prof")
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        run_id = started.run.id
        job_id = started.job.id

    before = datetime.now(UTC)
    async with session_scope() as session:
        outcome = await claim_and_process_keyword_job(session, gw)
        assert outcome is not None
        assert outcome["outcome"] == "retry_wait"

    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        job = await session.get(Job, job_id)
        assert run is not None and job is not None
        assert job.state == "retry_wait"
        assert run.state == "running"
        assert job.available_at is not None
        available = job.available_at
        if available.tzinfo is None:
            available = available.replace(tzinfo=UTC)
        delay = (available - before).total_seconds()
        assert 25 <= delay <= 40  # first transient attempt → 30s

        query = (
            await session.execute(
                select(DiscoveryRunQuery).where(
                    DiscoveryRunQuery.run_id == run_id,
                    DiscoveryRunQuery.query_kind == "global_message",
                )
            )
        ).scalar_one()
        assert query.state == "retry_wait"
        assert query.error_code == "transient_error"


@pytest.mark.asyncio
async def test_restart_recovers_stale_keyword_lease(db_env) -> None:
    assert LEASE_SECONDS == JOB_LEASE_SECONDS
    gw = FakeTelegramGateway()
    group = make_source(telegram_id=88, username="g88", source_type="megagroup")
    gw.register_source("g88", group)
    gw.set_global_hits(
        [make_hit(source=group, message_id=1, excerpt="нужен сайт", published_at=_fresh())]
    )
    gw.set_directory_results([])
    gw.set_quota(free_slot_available=False, premium_required=True)

    async with session_scope() as session:
        profile = await _make_profile(session, name="restart-prof")
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        run_id = started.run.id
        job = started.job
        job.state = "running"
        job.owner = "crashed-worker"
        job.lease_until = datetime.now(UTC) - timedelta(seconds=5)
        await session.flush()

    async with session_scope() as session:
        outcome = await claim_and_process_keyword_job(session, gw, owner="recovery-worker")
        assert outcome is not None
        assert outcome["outcome"] in ("succeeded", "partial")

    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        assert run is not None
        assert run.state in ("succeeded", "partial")
        job = (
            await session.execute(
                select(Job).where(Job.dedupe_key == f"keyword_discovery:run:{run_id}")
            )
        ).scalar_one()
        assert job.state == "succeeded"


@pytest.mark.asyncio
async def test_registry_known_source_suppressed_src031(db_env) -> None:
    """AT-SRC-031: registry telegram_id gets no evidence/opportunity/deep queries."""
    import json

    gw = FakeTelegramGateway()
    known = make_source(
        telegram_id=42,
        username="known_chat",
        source_type="megagroup",
        title="Known",
    )
    fresh = make_source(
        telegram_id=99,
        username="fresh_chat",
        source_type="megagroup",
        title="Fresh",
    )
    gw.register_source("known_chat", known)
    gw.register_source("fresh_chat", fresh)
    gw.set_global_hits(
        [
            make_hit(
                source=known,
                message_id=1,
                excerpt="нужен сайт known",
                published_at=_fresh(),
            ),
            make_hit(
                source=fresh,
                message_id=2,
                excerpt="нужен сайт fresh",
                published_at=_fresh(1),
            ),
        ]
    )
    gw.set_directory_results([known, fresh])
    gw.set_quota(free_slot_available=True)
    gw.set_public_post_hits("нужен сайт", [])

    async with session_scope() as session:
        session.add(
            TelegramSource(
                telegram_id=42,
                username_normalized="known_chat",
                title="Known",
                source_type="megagroup",
                public_url="https://t.me/known_chat",
                lifecycle_state="monitoring",
                quality_score=3,
            )
        )
        profile = await _make_profile(session, name="suppress-prof")
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        run_id = started.run.id

    async with session_scope() as session:
        outcome = await claim_and_process_keyword_job(session, gw)
        assert outcome is not None
        assert outcome["outcome"] in ("succeeded", "partial")

    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        assert run is not None
        counters = json.loads(run.counters_json or "{}")
        assert int(counters.get("registry_suppressed", 0)) >= 1

        evidence_ids = set(
            (
                await session.execute(
                    select(SourceDiscoveryEvidence.source_telegram_id).where(
                        SourceDiscoveryEvidence.run_id == run_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert 42 not in evidence_ids
        assert 99 in evidence_ids

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
        assert 42 not in opp_ids
        assert 99 in opp_ids

        deep_for_known = list(
            (
                await session.execute(
                    select(DiscoveryRunQuery).where(
                        DiscoveryRunQuery.run_id == run_id,
                        DiscoveryRunQuery.query_kind == "source_verification",
                        DiscoveryRunQuery.source_telegram_id == 42,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert deep_for_known == []


@pytest.mark.asyncio
async def test_dismissed_source_suppressed_src032(db_env) -> None:
    """AT-SRC-032: dismissed opportunity never reappears; D-069 also hides prior shown peers."""
    import json

    gw = FakeTelegramGateway()
    hidden = make_source(
        telegram_id=52,
        username="hidden_chat",
        source_type="megagroup",
        title="Hidden",
    )
    fresh = make_source(
        telegram_id=99,
        username="fresh_chat",
        source_type="megagroup",
        title="Fresh",
    )
    newer = make_source(
        telegram_id=100,
        username="newer_chat",
        source_type="megagroup",
        title="Newer",
    )
    hidden_renamed = make_source(
        telegram_id=52,
        username="hidden_alias",
        source_type="megagroup",
        title="Hidden Alias",
    )
    gw.register_source("hidden_chat", hidden)
    gw.register_source("hidden_alias", hidden_renamed)
    gw.register_source("fresh_chat", fresh)
    gw.register_source("newer_chat", newer)
    gw.set_directory_results([hidden_renamed, fresh, newer])
    gw.set_quota(free_slot_available=True)
    gw.set_public_post_hits("нужен сайт", [])

    async with session_scope() as session:
        profile = await _make_profile(session, name="dismiss-prof")
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        run1_id = started.run.id

    gw.set_global_hits(
        [
            make_hit(
                source=hidden,
                message_id=1,
                excerpt="нужен сайт hidden",
                published_at=_fresh(),
            ),
            make_hit(
                source=fresh,
                message_id=2,
                excerpt="нужен сайт fresh",
                published_at=_fresh(1),
            ),
        ]
    )
    async with session_scope() as session:
        outcome = await claim_and_process_keyword_job(session, gw)
        assert outcome is not None

    async with session_scope() as session:
        hidden_snapshot = (
            await session.execute(
                select(SourceOpportunitySnapshot).where(
                    SourceOpportunitySnapshot.run_id == run1_id,
                    SourceOpportunitySnapshot.source_telegram_id == 52,
                )
            )
        ).scalar_one()
        await dismiss_opportunity(
            session,
            opportunity_id=hidden_snapshot.id,
            version=hidden_snapshot.version,
            reason="hidden_by_operator",
        )

    async with session_scope() as session:
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        run2_id = started.run.id

    gw.set_global_hits(
        [
            make_hit(
                source=hidden_renamed,
                message_id=11,
                excerpt="нужен сайт hidden again",
                published_at=_fresh(),
            ),
            make_hit(
                source=fresh,
                message_id=12,
                excerpt="нужен сайт fresh again",
                published_at=_fresh(1),
            ),
            make_hit(
                source=newer,
                message_id=13,
                excerpt="нужен сайт newer",
                published_at=_fresh(2),
            ),
        ]
    )
    async with session_scope() as session:
        outcome = await claim_and_process_keyword_job(session, gw)
        assert outcome is not None
        assert outcome["outcome"] in ("succeeded", "partial")

    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run2_id)
        assert run is not None
        counters = json.loads(run.counters_json or "{}")
        assert int(counters.get("dismissed_suppressed", 0)) >= 1
        # Peer 99 was presented in run1 → durable presented suppress (D-069).
        assert int(counters.get("presented_suppressed", 0)) >= 1
        assert int(counters.get("cooldown_suppressed", 0)) == int(
            counters.get("presented_suppressed", 0)
        )

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
        assert 52 not in evidence_ids
        assert 99 not in evidence_ids
        assert 100 in evidence_ids

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
        assert 52 not in opp_ids
        assert 99 not in opp_ids
        assert 100 in opp_ids

        deep_for_hidden = list(
            (
                await session.execute(
                    select(DiscoveryRunQuery).where(
                        DiscoveryRunQuery.run_id == run2_id,
                        DiscoveryRunQuery.query_kind == "source_verification",
                        DiscoveryRunQuery.source_telegram_id == 52,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert deep_for_hidden == []

