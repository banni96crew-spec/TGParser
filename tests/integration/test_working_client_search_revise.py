"""Focused revise tests: FloodWait/crash resume, pool дожим, evidence priority, gate empty."""

from __future__ import annotations

import json
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
from telegram_lead_discovery.infrastructure.paths import database_path, ensure_directories
from telegram_lead_discovery.source_discovery.keyword_run import start_keyword_discovery_run
from telegram_lead_discovery.source_discovery.keyword_search import (
    MAX_EVIDENCE_PER_RUN,
    MAX_NOISE_EVIDENCE_PER_RUN,
)
from telegram_lead_discovery.source_discovery.profile_service import (
    create_keyword_discovery_profile,
)
from telegram_lead_discovery.source_discovery.worker import (
    HISTORY_SCAN_QUERY_TEXT,
    _finished_verification_sources,
    _load_history_cursor,
    _TERMINAL_VERIFICATION_STATES,
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


def _client_text(n: int) -> str:
    return f"Нужно разработать интернет-магазин номер {n}, бюджет 150 000 ₽."


def _noise_text(n: int) -> str:
    return f"#Помогу с сайтом на Tilda под ключ вариант {n}"


async def _make_profile(session, *, name: str = "revise-kw"):
    return await create_keyword_discovery_profile(
        session,
        name=name,
        post_queries=["нужен сайт"],
        directory_queries=["pool"],  # FakeGateway matches query ⊂ title/username
        source_scope="groups",
    )


@pytest.mark.asyncio
async def test_finished_verification_excludes_running_and_retry_wait(db_env) -> None:
    async with session_scope() as session:
        profile = await _make_profile(session)
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        run = started.run
        for state, tid in (
            ("succeeded", 1),
            ("failed", 2),
            ("running", 3),
            ("retry_wait", 4),
            ("cancelled", 5),
        ):
            session.add(
                DiscoveryRunQuery(
                    run_id=run.id,
                    ordinal=100 + tid,
                    query_kind="source_verification",
                    query_text=HISTORY_SCAN_QUERY_TEXT,
                    source_telegram_id=tid,
                    state=state,
                    started_at=datetime.now(UTC),
                )
            )
        await session.flush()

        class _Ctx:
            pass

        ctx = _Ctx()
        ctx.session = session
        ctx.run = run
        done = await _finished_verification_sources(ctx)  # type: ignore[arg-type]
        assert done == {1, 2, 5}
        assert "running" not in _TERMINAL_VERIFICATION_STATES
        assert "retry_wait" not in _TERMINAL_VERIFICATION_STATES


@pytest.mark.asyncio
async def test_flood_wait_then_new_context_resumes_same_cursor(db_env) -> None:
    gw = FakeTelegramGateway()
    src = make_source(
        telegram_id=501,
        username="flood_chat",
        source_type="megagroup",
        title="Flood pool Chat Title",
    )
    gw.register_source("flood_chat", src)
    gw.set_directory_results([src])
    gw.set_quota(free_slot_available=False, premium_required=False, stars_amount=0)
    gw.set_global_hits([])
    msgs = [
        TelegramMessageDTO(
            schema_version=1,
            source_id=0,
            telegram_message_id=100 - i,
            published_at=_fresh(i),
            text=_client_text(i),
            telegram_peer_id=501,
            permalink=f"https://t.me/flood_chat/{100 - i}",
        )
        for i in range(10)
    ]
    gw.register_messages_for_peer(501, msgs)

    async with session_scope() as session:
        profile = await _make_profile(session, name="flood-resume")
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        run_id = started.run.id
        job_id = started.job.id

    until = datetime.now(UTC) + timedelta(minutes=10)
    gw.set_flood_wait(until, "iter_history")

    async with session_scope() as session:
        job = await session.get(Job, job_id)
        outcome = await process_keyword_discovery_job(session, job, gw)  # type: ignore[arg-type]
        assert outcome["outcome"] in ("retry_wait", "waiting", "flood_wait") or outcome.get(
            "error"
        ) in (None, "flood_wait")

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
        cursor = _load_history_cursor(q)
        assert cursor.get("stop_reason") == "flood_wait"
        assert "scanned" in cursor
        run = await session.get(DiscoveryRun, run_id)
        assert run is not None
        payload = json.loads(run.cursor_json or "{}")
        assert payload.get("directory_pool") or payload.get("acquisition_pool")

    # Clear flood; make available_at due; new context/session resumes.
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
        job = (
            await session.execute(select(Job).where(Job.id == job_id))
        ).scalar_one()
        job.state = "queued"
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.flush()

    async with session_scope() as session:
        outcome = await claim_and_process_keyword_job(session, gw)
        assert outcome is not None

    async with session_scope() as session:
        evidence = list(
            (
                await session.execute(
                    select(SourceDiscoveryEvidence).where(
                        SourceDiscoveryEvidence.run_id == run_id,
                        SourceDiscoveryEvidence.source_telegram_id == 501,
                    )
                )
            )
            .scalars()
            .all()
        )
        # Idempotent: no duplicate message ids
        ids = [e.telegram_message_id for e in evidence]
        assert len(ids) == len(set(ids))
        # Metadata preserved from directory pool (not hardcoded title=username)
        if evidence:
            assert evidence[0].source_title == "Flood pool Chat Title"
            assert evidence[0].source_type == "megagroup"


@pytest.mark.asyncio
async def test_crash_running_state_is_resumed_not_skipped(db_env) -> None:
    gw = FakeTelegramGateway()
    src = make_source(
        telegram_id=777,
        username="crash_chat",
        source_type="channel",
        title="Crash Channel",
    )
    gw.register_source("crash_chat", src)
    gw.set_directory_results([src])
    gw.set_quota(free_slot_available=False)
    gw.set_global_hits([])
    gw.register_messages_for_peer(
        777,
        [
            TelegramMessageDTO(
                schema_version=1,
                source_id=0,
                telegram_message_id=50 - i,
                published_at=_fresh(i),
                text=_client_text(i + 1),
                telegram_peer_id=777,
            )
            for i in range(8)
        ],
    )

    async with session_scope() as session:
        profile = await _make_profile(session, name="crash-resume")
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        run = started.run
        run.state = "running"
        run.phase = "H"
        run.cursor_json = json.dumps(
            {
                "directory_pool": [
                    {
                        "telegram_id": 777,
                        "username": "crash_chat",
                        "title": "Crash Channel",
                        "source_type": "channel",
                        "public_url": "https://t.me/crash_chat",
                    }
                ],
                "acquisition_pool": [
                    {
                        "telegram_id": 777,
                        "username": "crash_chat",
                        "title": "Crash Channel",
                        "source_type": "channel",
                        "public_url": "https://t.me/crash_chat",
                    }
                ],
                "acquisition_pool_cursor": 1,
            },
            ensure_ascii=False,
        )
        # Mark seed queries done so worker proceeds to deep verification.
        for q in (
            await session.execute(
                select(DiscoveryRunQuery).where(DiscoveryRunQuery.run_id == run.id)
            )
        ).scalars():
            q.state = "succeeded"
            q.finished_at = datetime.now(UTC)
        session.add(
            DiscoveryRunQuery(
                run_id=run.id,
                ordinal=90,
                query_kind="source_verification",
                query_text=HISTORY_SCAN_QUERY_TEXT,
                source_telegram_id=777,
                state="running",
                started_at=datetime.now(UTC),
                cursor_json=json.dumps(
                    {"offset_id": 48, "scanned": 2, "distinct_hashes": [], "noise_kept": 0}
                ),
            )
        )
        job = started.job
        job.state = "queued"
        await session.flush()
        run_id = run.id

    async with session_scope() as session:
        outcome = await claim_and_process_keyword_job(session, gw)
        assert outcome is not None

    async with session_scope() as session:
        q = (
            await session.execute(
                select(DiscoveryRunQuery).where(
                    DiscoveryRunQuery.run_id == run_id,
                    DiscoveryRunQuery.query_kind == "source_verification",
                    DiscoveryRunQuery.source_telegram_id == 777,
                )
            )
        ).scalars().first()
        assert q is not None
        assert q.state == "succeeded"
        evidence_n = (
            await session.execute(
                select(func.count())
                .select_from(SourceDiscoveryEvidence)
                .where(
                    SourceDiscoveryEvidence.run_id == run_id,
                    SourceDiscoveryEvidence.source_telegram_id == 777,
                )
            )
        ).scalar_one()
        assert evidence_n >= 1


@pytest.mark.asyncio
async def test_empty_finalize_writes_gate_fail(db_env) -> None:
    gw = FakeTelegramGateway()
    gw.set_quota(free_slot_available=False)
    gw.set_global_hits([])
    gw.set_directory_results([])

    async with session_scope() as session:
        profile = await _make_profile(session, name="empty-gate")
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        run_id = started.run.id

    async with session_scope() as session:
        outcome = await claim_and_process_keyword_job(session, gw)
        assert outcome is not None

    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        assert run is not None
        counters = json.loads(run.counters_json or "{}")
        assert counters.get("gate_status") == "fail"
        assert counters.get("quality_sources") == 0
        assert counters.get("globally_distinct_client_requests") == 0
        assert counters.get("evidence_count") == 0


@pytest.mark.asyncio
async def test_noise_filled_quota_still_persists_later_qualified(db_env) -> None:
    """Noise hits MAX_NOISE budget first; later quality source still persists 7 clients."""
    from telegram_lead_discovery.source_discovery import worker as worker_mod

    gw = FakeTelegramGateway()
    noise_src = make_source(
        telegram_id=1001,
        username="noise_src",
        source_type="megagroup",
        title="Noise pool",
    )
    quality_src = make_source(
        telegram_id=1002,
        username="quality_src",
        source_type="megagroup",
        title="Quality pool",
    )
    gw.register_source("noise_src", noise_src)
    gw.register_source("quality_src", quality_src)
    gw.set_directory_results([noise_src, quality_src])
    gw.set_quota(free_slot_available=False)
    # Seed evidence via global so both enter pool with noise first by rank/id.
    gw.set_global_hits(
        [
            make_hit(
                source=noise_src,
                message_id=1,
                excerpt=_noise_text(0),
                published_at=_fresh(),
            ),
            make_hit(
                source=quality_src,
                message_id=2,
                excerpt=_client_text(0),
                published_at=_fresh(),
            ),
        ]
    )
    # Fill noise peer history with many hard-exclusion messages.
    gw.register_messages_for_peer(
        1001,
        [
            TelegramMessageDTO(
                schema_version=1,
                source_id=0,
                telegram_message_id=9000 - i,
                published_at=_fresh(min(i, 10)),
                text=_noise_text(i),
                telegram_peer_id=1001,
            )
            for i in range(MAX_NOISE_EVIDENCE_PER_RUN + 5)
        ],
    )
    gw.register_messages_for_peer(
        1002,
        [
            TelegramMessageDTO(
                schema_version=1,
                source_id=0,
                telegram_message_id=8000 - i,
                published_at=_fresh(i),
                text=_client_text(i + 1),
                telegram_peer_id=1002,
            )
            for i in range(8)
        ],
    )

    # Shrink total soft cap so noise would starve qualified under old logic.
    monkey_total = MAX_NOISE_EVIDENCE_PER_RUN + 5
    original_max = worker_mod.MAX_EVIDENCE_PER_RUN
    worker_mod.MAX_EVIDENCE_PER_RUN = monkey_total
    try:
        async with session_scope() as session:
            profile = await _make_profile(session, name="evidence-prio")
            started = await start_keyword_discovery_run(
                session, profile_id=profile.profile.id
            )
            run_id = started.run.id

        async with session_scope() as session:
            outcome = await claim_and_process_keyword_job(session, gw)
            assert outcome is not None

        async with session_scope() as session:
            q_ev = list(
                (
                    await session.execute(
                        select(SourceDiscoveryEvidence).where(
                            SourceDiscoveryEvidence.run_id == run_id,
                            SourceDiscoveryEvidence.source_telegram_id == 1002,
                            SourceDiscoveryEvidence.is_qualified.is_(True),
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(q_ev) >= 7
            # Rule IDs persisted
            assert any(
                json.loads(getattr(e, "matched_rule_ids_json", "[]") or "[]") for e in q_ev
            )
    finally:
        worker_mod.MAX_EVIDENCE_PER_RUN = original_max


@pytest.mark.asyncio
async def test_pool_continues_past_first_25_until_gate(db_env, monkeypatch: pytest.MonkeyPatch) -> None:
    from telegram_lead_discovery.source_discovery import worker as worker_mod

    monkeypatch.setattr(worker_mod, "DIRECTORY_PEER_LIMIT", 40)
    gw = FakeTelegramGateway()
    sources = []
    for i in range(30):
        s = make_source(
            telegram_id=2000 + i,
            username=f"pool_{i}",
            source_type="megagroup",
            title=f"Pool {i}",
        )
        sources.append(s)
        gw.register_source(f"pool_{i}", s)
        if i < 25:
            # Non-quality: empty / noise only
            gw.register_messages_for_peer(
                2000 + i,
                [
                    TelegramMessageDTO(
                        schema_version=1,
                        source_id=0,
                        telegram_message_id=1,
                        published_at=_fresh(),
                        text="сегодня отличная погода",
                        telegram_peer_id=2000 + i,
                    )
                ],
            )
        else:
            gw.register_messages_for_peer(
                2000 + i,
                [
                    TelegramMessageDTO(
                        schema_version=1,
                        source_id=0,
                        telegram_message_id=100 - j,
                        published_at=_fresh(j),
                        text=_client_text(j + 1 + i * 10),
                        telegram_peer_id=2000 + i,
                    )
                    for j in range(8)
                ],
            )
    gw.set_directory_results(sources)
    gw.set_quota(free_slot_available=False)
    gw.set_global_hits([])

    async with session_scope() as session:
        profile = await _make_profile(session, name="pool-dojim")
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        run_id = started.run.id

    async with session_scope() as session:
        outcome = await claim_and_process_keyword_job(session, gw)
        assert outcome is not None

    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        assert run is not None
        counters = json.loads(run.counters_json or "{}")
        assert counters.get("quality_sources", 0) >= 5
        assert counters.get("globally_distinct_client_requests", 0) >= 35
        assert counters.get("gate_status") == "pass"
        # Verified more than soft preference of 25
        ver_q = (
            await session.execute(
                select(func.count())
                .select_from(DiscoveryRunQuery)
                .where(
                    DiscoveryRunQuery.run_id == run_id,
                    DiscoveryRunQuery.query_kind == "source_verification",
                )
            )
        ).scalar_one()
        assert ver_q >= 30


@pytest.mark.asyncio
async def test_directory_pool_survives_restart(db_env) -> None:
    gw = FakeTelegramGateway()
    only_dir = make_source(
        telegram_id=3333,
        username="dir_only",
        source_type="channel",
        title="Directory Only pool Title",
    )
    gw.register_source("dir_only", only_dir)
    gw.set_directory_results([only_dir])
    gw.set_global_hits([])
    gw.set_quota(free_slot_available=False)
    until = datetime.now(UTC) + timedelta(minutes=5)
    gw.set_flood_wait(until, "iter_history")
    gw.register_messages_for_peer(
        3333,
        [
            TelegramMessageDTO(
                schema_version=1,
                source_id=0,
                telegram_message_id=10,
                published_at=_fresh(),
                text=_client_text(1),
                telegram_peer_id=3333,
            )
        ],
    )

    async with session_scope() as session:
        profile = await _make_profile(session, name="dir-pool")
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        run_id = started.run.id
        job_id = started.job.id

    async with session_scope() as session:
        await claim_and_process_keyword_job(session, gw)

    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        assert run is not None
        payload = json.loads(run.cursor_json or "{}")
        pool = payload.get("directory_pool") or []
        assert any(int(p["telegram_id"]) == 3333 for p in pool)
        assert any(p.get("title") == "Directory Only pool Title" for p in pool)

    gw.clear_flood_wait()
    async with session_scope() as session:
        for q in (
            await session.execute(
                select(DiscoveryRunQuery).where(
                    DiscoveryRunQuery.run_id == run_id,
                    DiscoveryRunQuery.state == "retry_wait",
                )
            )
        ).scalars():
            q.available_at = datetime.now(UTC) - timedelta(seconds=1)
        job = await session.get(Job, job_id)
        assert job is not None
        job.state = "queued"
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.flush()

    async with session_scope() as session:
        await claim_and_process_keyword_job(session, gw)

    async with session_scope() as session:
        snaps = list(
            (
                await session.execute(
                    select(SourceOpportunitySnapshot).where(
                        SourceOpportunitySnapshot.run_id == run_id,
                        SourceOpportunitySnapshot.source_telegram_id == 3333,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert snaps
        assert snaps[0].title == "Directory Only pool Title"
        assert snaps[0].source_type == "channel"
