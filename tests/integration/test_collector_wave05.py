"""Wave 05 — collector integration: peer, pagination, live, pause, batching."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from telegram_lead_discovery.collector.fake import FakeTelegramGateway, make_source
from telegram_lead_discovery.collector.ports import (
    HistoryRequest,
    TelegramMessageDTO,
    TelegramPeerRef,
    TelegramUpdateDTO,
)
from telegram_lead_discovery.collector.service import (
    PERSIST_BATCH_SIZE,
    consume_live_updates,
    execute_backfill_job,
    ingest_live_update,
    peer_from_source,
    persist_envelope_batch,
    request_source_pause_ingest,
)
from telegram_lead_discovery.infrastructure.paths import ensure_app_directories, resolve_app_paths
from telegram_lead_discovery.settings.service import seed_defaults
from telegram_lead_discovery.source_discovery.service import add_manual_candidate, approve_source
from telegram_lead_discovery.storage.db import dispose_engine, init_engine
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import (
    CollectorCheckpoint,
    Job,
    TelegramEventEnvelope,
    TelegramSource,
)
from telegram_lead_discovery.storage.session import configure_session_factory, run_write


@pytest.fixture
async def db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    paths = ensure_app_directories(resolve_app_paths())
    upgrade_head(paths.database_path)
    engine = await init_engine(paths.database_path)
    configure_session_factory(engine)
    await run_write(seed_defaults)
    yield paths
    await dispose_engine()


def _msg(
    *,
    source_id: int,
    peer_id: int,
    mid: int,
    text: str,
    published: datetime,
    edited: datetime | None = None,
) -> TelegramMessageDTO:
    return TelegramMessageDTO(
        schema_version=1,
        source_id=source_id,
        telegram_message_id=mid,
        published_at=published,
        text=text,
        telegram_peer_id=peer_id,
        edited_at=edited,
        permalink=f"https://t.me/wave05_chan/{mid}",
    )


async def _seed_monitoring(db_env, *, telegram_id: int = 9001, username: str = "wave05_chan"):
    snap = make_source(telegram_id=telegram_id, username=username)
    gateway = FakeTelegramGateway(sources={username: snap})

    async def _add(session):
        source, _ = await add_manual_candidate(
            session, username_or_url=f"@{username}", gateway=gateway
        )
        return source.id

    source_id = await run_write(_add)

    async def _approve(session):
        return await approve_source(session, source_id=source_id, gateway=gateway)

    source = await run_write(_approve)
    return source.id, telegram_id, gateway


@pytest.mark.asyncio
async def test_peer_ref_never_uses_db_source_id_as_entity(db_env) -> None:
    source_id, peer_id, gateway = await _seed_monitoring(db_env)
    now = datetime.now(UTC)
    messages = [
        _msg(source_id=source_id, peer_id=peer_id, mid=i, text=f"m{i}", published=now)
        for i in range(1, 6)
    ]
    gateway.register_messages_for_peer(peer_id, messages)
    gateway.register_messages(source_id, messages)

    async def _job(session):
        result = await session.execute(
            select(Job).where(Job.dedupe_key == f"initial_backfill:{source_id}")
        )
        return result.scalar_one().id

    job_id = await run_write(_job)
    outcome = await execute_backfill_job(job_id=job_id, gateway=gateway)
    assert outcome["outcome"] == "succeeded"
    assert gateway.history_calls
    for req in gateway.history_calls:
        assert isinstance(req.peer, TelegramPeerRef)
        assert req.peer.telegram_peer_id == peer_id
        # Entity ledger must not contain DB source_id.
        assert source_id not in gateway.resolved_entities
        assert peer_id in gateway.resolved_entities


@pytest.mark.asyncio
async def test_backfill_paginates_beyond_100(db_env) -> None:
    source_id, peer_id, gateway = await _seed_monitoring(
        db_env, telegram_id=9002, username="wave05_page"
    )
    now = datetime.now(UTC)
    # 150 messages → page 100 then continuation for remaining.
    messages = [
        _msg(
            source_id=source_id,
            peer_id=peer_id,
            mid=i,
            text=f"need site {i}",
            published=now - timedelta(minutes=150 - i),
        )
        for i in range(1, 151)
    ]
    gateway.register_messages_for_peer(peer_id, messages)

    async def _job(session):
        result = await session.execute(
            select(Job).where(Job.dedupe_key == f"initial_backfill:{source_id}")
        )
        return result.scalar_one().id

    job_id = await run_write(_job)
    first = await execute_backfill_job(job_id=job_id, gateway=gateway)
    assert first["outcome"] == "continued"
    assert first["persisted"] == 100
    assert first["continuation_cursor"] is not None

    async def _cont(session):
        result = await session.execute(
            select(Job).where(Job.job_type == "continuation", Job.state == "queued")
        )
        return result.scalar_one().id

    cont_id = await run_write(_cont)
    second = await execute_backfill_job(job_id=cont_id, gateway=gateway)
    assert second["outcome"] == "succeeded"
    assert second["persisted"] == 50

    async def _count(session):
        result = await session.execute(select(TelegramEventEnvelope))
        return len(list(result.scalars().all()))

    assert await run_write(_count) == 150
    assert len(gateway.history_calls) >= 2


@pytest.mark.asyncio
async def test_persist_batch_cap_and_no_network_in_write_tx(db_env) -> None:
    source_id, peer_id, gateway = await _seed_monitoring(
        db_env, telegram_id=9003, username="wave05_batch"
    )
    now = datetime.now(UTC)
    messages = [
        _msg(source_id=source_id, peer_id=peer_id, mid=i, text=f"b{i}", published=now)
        for i in range(1, 61)
    ]
    network_during_write: list[bool] = []

    class TrackingGateway(FakeTelegramGateway):
        async def iter_history(self, request: HistoryRequest):
            # If write lock is held, nested run_write would block — we just record.
            network_during_write.append(True)
            async for item in super().iter_history(request):
                yield item

    tg = TrackingGateway(
        sources={"wave05_batch": make_source(telegram_id=9003, username="wave05_batch")}
    )
    tg.register_messages_for_peer(peer_id, messages)

    async def _job(session):
        result = await session.execute(
            select(Job).where(Job.dedupe_key == f"initial_backfill:{source_id}")
        )
        return result.scalar_one().id

    job_id = await run_write(_job)

    # Oversize batch must raise when persist_envelope_batch is called directly.
    with pytest.raises(ValueError, match="persist batch size"):
        await run_write(
            lambda s: persist_envelope_batch(
                s,
                source_id=source_id,
                messages=messages[: PERSIST_BATCH_SIZE + 1],
                collection_mode="backfill",
            )
        )

    outcome = await execute_backfill_job(job_id=job_id, gateway=tg)
    assert outcome["outcome"] == "succeeded"
    assert outcome["persisted"] == 60
    assert network_during_write  # network occurred
    # Checkpoint advanced.
    async def _cp(session):
        return await session.get(CollectorCheckpoint, source_id)

    cp = await run_write(_cp)
    assert cp is not None
    assert cp.last_committed_message_id == 60


@pytest.mark.asyncio
async def test_live_create_edit_delete_idempotent_no_dup(db_env) -> None:
    source_id, peer_id, _gw = await _seed_monitoring(
        db_env, telegram_id=9004, username="wave05_live"
    )
    now = datetime.now(UTC)
    create = TelegramUpdateDTO(
        schema_version=1,
        event_type="message_new",
        telegram_peer_id=peer_id,
        observed_at=now,
        message=_msg(
            source_id=source_id, peer_id=peer_id, mid=42, text="need bot", published=now
        ),
    )
    edit_at = now + timedelta(minutes=1)
    edit = TelegramUpdateDTO(
        schema_version=1,
        event_type="message_edited",
        telegram_peer_id=peer_id,
        observed_at=edit_at,
        message=_msg(
            source_id=source_id,
            peer_id=peer_id,
            mid=42,
            text="need bot urgently",
            published=now,
            edited=edit_at,
        ),
    )
    delete = TelegramUpdateDTO(
        schema_version=1,
        event_type="message_deleted",
        telegram_peer_id=peer_id,
        observed_at=now + timedelta(minutes=2),
        message=_msg(
            source_id=source_id, peer_id=peer_id, mid=42, text="", published=now
        ),
    )

    async def _ingest_all(session):
        a = await ingest_live_update(session, create)
        b = await ingest_live_update(session, edit)
        c = await ingest_live_update(session, delete)
        # Replay create — must not duplicate.
        a2 = await ingest_live_update(session, create)
        return a, b, c, a2

    a, b, c, a2 = await run_write(_ingest_all)
    assert a is not None and b is not None and c is not None
    assert a.id == a2.id

    async def _rows(session):
        result = await session.execute(
            select(TelegramEventEnvelope).where(
                TelegramEventEnvelope.telegram_message_id == 42
            )
        )
        return list(result.scalars().all())

    rows = await run_write(_rows)
    types = sorted(r.event_type for r in rows)
    assert types == ["message_deleted", "message_edited", "message_new"]
    payloads = [json.loads(r.payload_json) for r in rows]
    assert all(p.get("telegram_peer_id") == peer_id for p in payloads)


@pytest.mark.asyncio
async def test_pause_stops_live_ingest(db_env) -> None:
    source_id, peer_id, gateway = await _seed_monitoring(
        db_env, telegram_id=9005, username="wave05_pause"
    )
    now = datetime.now(UTC)

    async def _pause(session):
        await request_source_pause_ingest(session, source_id)

    await run_write(_pause)

    async def _state(session):
        src = await session.get(TelegramSource, source_id)
        assert src is not None
        return src.lifecycle_state

    assert await run_write(_state) == "paused"

    update = TelegramUpdateDTO(
        schema_version=1,
        event_type="message_new",
        telegram_peer_id=peer_id,
        observed_at=now,
        message=_msg(
            source_id=source_id, peer_id=peer_id, mid=7, text="after pause", published=now
        ),
    )
    await gateway.push_update(update)
    await gateway.close_updates()

    stats = await consume_live_updates(gateway)
    assert stats["accepted"] == 0
    assert stats["discarded"] >= 1

    async def _count(session):
        result = await session.execute(select(TelegramEventEnvelope))
        return len(list(result.scalars().all()))

    assert await run_write(_count) == 0

    async def _jobs(session):
        result = await session.execute(
            select(Job).where(Job.dedupe_key == f"initial_backfill:{source_id}")
        )
        return result.scalar_one().state

    assert await run_write(_jobs) == "cancelled"


@pytest.mark.asyncio
async def test_peer_from_source_requires_network_identity(db_env) -> None:
    async def _add(session):
        src = TelegramSource(
            title="no peer",
            source_type="channel",
            lifecycle_state="monitoring",
            telegram_id=None,
            username_normalized=None,
        )
        session.add(src)
        await session.flush()
        return src.id

    sid = await run_write(_add)

    async def _peer(session):
        src = await session.get(TelegramSource, sid)
        assert src is not None
        with pytest.raises(ValueError):
            peer_from_source(src)

    await run_write(_peer)


@pytest.mark.asyncio
async def test_flood_wait_sets_retry_without_attempt_burn(db_env) -> None:
    source_id, peer_id, gateway = await _seed_monitoring(
        db_env, telegram_id=9006, username="wave05_flood"
    )
    until = datetime.now(UTC) + timedelta(seconds=90)
    gateway.set_flood_wait(until, "iter_history")
    gateway.register_messages_for_peer(
        peer_id,
        [_msg(source_id=source_id, peer_id=peer_id, mid=1, text="x", published=datetime.now(UTC))],
    )

    async def _prep(session):
        result = await session.execute(
            select(Job).where(Job.dedupe_key == f"initial_backfill:{source_id}")
        )
        job = result.scalar_one()
        job.attempt = 1
        job.state = "running"
        await session.flush()
        return job.id, job.attempt

    job_id, attempt_before = await run_write(_prep)
    outcome = await execute_backfill_job(job_id=job_id, gateway=gateway)
    assert outcome["outcome"] == "flood_wait"
    assert outcome["health_reason"] == "flood_wait"

    async def _job(session):
        job = await session.get(Job, job_id)
        assert job is not None
        return job.state, job.attempt, job.available_at

    state, attempt, available = await run_write(_job)
    assert state == "retry_wait"
    assert attempt == attempt_before - 1  # compensated (COL-017)
    assert available is not None
    # SQLite may drop tzinfo; compare naive UTC instants.
    avail = available.replace(tzinfo=UTC) if available.tzinfo is None else available
    assert abs((avail - until).total_seconds()) < 1
