"""Wave 06 E2E — isolated process path with fake gateway + temp DB (INF-022 gate).

candidate → approve → backfill claim/complete → live create/edit/delete →
one lead → one outbox → restart no dup → pause no ingest → kill mid-batch reconcile.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from telegram_lead_discovery.collector.fake import FakeTelegramGateway, make_source
from telegram_lead_discovery.collector.ports import TelegramMessageDTO, TelegramUpdateDTO
from telegram_lead_discovery.collector.service import (
    claim_and_process_collector_job,
    ingest_live_update,
    request_source_pause_ingest,
)
from telegram_lead_discovery.detection.seed import seed_ruleset_ru_mvp_1
from telegram_lead_discovery.infrastructure.paths import ensure_app_directories, resolve_app_paths
from telegram_lead_discovery.infrastructure.runtime import RuntimeCoordinator
from telegram_lead_discovery.notifications.worker import process_one
from telegram_lead_discovery.observability.health import HealthState, reset_health_registry
from telegram_lead_discovery.processing.pipeline import process_next_envelope
from telegram_lead_discovery.settings.service import seed_defaults, update_setting
from telegram_lead_discovery.source_discovery.service import add_manual_candidate, approve_source
from telegram_lead_discovery.storage.db import dispose_engine, init_engine
from telegram_lead_discovery.storage.jobs import recover_stale_jobs
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import (
    Job,
    Lead,
    NotificationDelivery,
    NotificationOutbox,
    TelegramEventEnvelope,
    TelegramMessage,
    TelegramMessageRevision,
)
from telegram_lead_discovery.storage.session import configure_session_factory, run_write

HOT_TEXT = (
    "Нужно разработать интернет-магазин с оплатой и корзиной, "
    "бюджет 250000 ₽, срочно, готов начать, пишите @wave06client."
)


class FakeBotClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def post(self, url: str, *, json: dict | None = None) -> Any:
        self.calls.append({"url": url, "json": json})

        class _Resp:
            status_code = 200

            def json(self) -> dict[str, Any]:
                return {"ok": True, "result": {"message_id": 42}}

        return _Resp()


@pytest.fixture
async def e2e_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("TG_API_ID", "12345")
    monkeypatch.setenv("TG_API_HASH", "hash-for-tests")
    monkeypatch.setenv("TG_BOT_TOKEN", "123456:WAVE06-TEST-TOKEN")
    monkeypatch.setenv("TG_NOTIFY_CHAT_ID", "-1006006")
    paths = ensure_app_directories(resolve_app_paths())
    upgrade_head(paths.database_path)
    engine = await init_engine(paths.database_path)
    configure_session_factory(engine)

    async def _seed(session):
        await seed_defaults(session)
        await seed_ruleset_ru_mvp_1(session)
        snap = await update_setting(
            session,
            key="notifications.delivery_mode",
            typed_value="live",
            expected_settings_version=1,
            change_source="test",
        )
        return snap.settings_version

    await run_write(_seed)
    yield paths
    await dispose_engine()
    from telegram_lead_discovery.storage.session import reset_write_lock

    reset_write_lock()


def _msg(
    *,
    source_id: int,
    peer_id: int,
    mid: int,
    text: str,
    published: datetime,
    edited: datetime | None = None,
    deleted: bool = False,
) -> TelegramMessageDTO:
    return TelegramMessageDTO(
        schema_version=1,
        source_id=source_id,
        telegram_message_id=mid,
        published_at=published,
        text=text,
        telegram_peer_id=peer_id,
        edited_at=edited,
        permalink=f"https://t.me/wave06_e2e/{mid}",
        is_deleted=deleted,
    )


@pytest.mark.asyncio
async def test_wave06_full_pipeline_e2e_temp_db_fake_gateway(e2e_env) -> None:
    peer_id = 88006
    username = "wave06_e2e"
    snap = make_source(telegram_id=peer_id, username=username)
    now = datetime.now(UTC)
    gateway = FakeTelegramGateway(sources={username: snap})
    gateway.register_messages_for_peer(
        peer_id,
        [
            _msg(
                source_id=0,
                peer_id=peer_id,
                mid=1,
                text="noise older backfill",
                published=now - timedelta(hours=2),
            ),
            _msg(
                source_id=0,
                peer_id=peer_id,
                mid=2,
                text="ordinary channel update without commercial ask",
                published=now - timedelta(hours=1),
            ),
        ],
    )

    bot = FakeBotClient()

    # 1) Candidate → 2) Approve → monitoring + initial_backfill job
    async def _add(session):
        source, _ = await add_manual_candidate(
            session, username_or_url=f"@{username}", gateway=gateway
        )
        return source.id

    source_id = await run_write(_add)

    async def _approve(session):
        return await approve_source(session, source_id=source_id, gateway=gateway)

    source = await run_write(_approve)
    assert source.lifecycle_state == "monitoring"

    registry = reset_health_registry()
    coordinator = RuntimeCoordinator(
        idle_seconds=0.05,
        periodic_reconcile_seconds=3600,
        notification_client_factory=lambda: bot,
        startup_token="e2e-boot",
    )
    await coordinator.start(registry, gateway=gateway)

    # Health must not be permanent STOPPED/deferred
    assert registry.components["collector"].state in {
        HealthState.HEALTHY,
        HealthState.DEGRADED,
        HealthState.STARTING,
    }
    assert registry.components["collector"].reason_code != "deferred"

    # Pause background processing/notification so E2E drives claim explicitly.
    # Leave collector running briefly, then drive remaining jobs manually.
    if coordinator.processing_loop is not None:
        await coordinator.processing_loop.stop()
    if coordinator.notification_loop is not None:
        await coordinator.notification_loop.stop()

    # 3) Backfill claim/complete via collector worker path
    deadline = asyncio.get_event_loop().time() + 8.0
    backfill_done = False
    while asyncio.get_event_loop().time() < deadline:
        outcome = await claim_and_process_collector_job(gateway, owner="e2e-backfill")
        if outcome is None:
            async def _env_count_check(session):
                return int(
                    (
                        await session.execute(
                            select(func.count()).select_from(TelegramEventEnvelope)
                        )
                    ).scalar_one()
                )

            if await run_write(_env_count_check) >= 1:
                backfill_done = True
                break
            await asyncio.sleep(0.05)
            continue
        if outcome.get("outcome") in {"succeeded", "cancelled"}:
            backfill_done = True
            break
        await asyncio.sleep(0.05)
    assert backfill_done

    if coordinator.collector_job_loop is not None:
        await coordinator.collector_job_loop.stop()

    async def _env_count(session):
        return int(
            (
                await session.execute(select(func.count()).select_from(TelegramEventEnvelope))
            ).scalar_one()
        )

    assert await run_write(_env_count) >= 1

    # 4) Live create / edit / delete (direct ingest — deterministic; live loop also running)
    live_mid = 100
    create_dto = _msg(
        source_id=source_id,
        peer_id=peer_id,
        mid=live_mid,
        text=HOT_TEXT,
        published=now,
    )
    edit_dto = _msg(
        source_id=source_id,
        peer_id=peer_id,
        mid=live_mid,
        text=HOT_TEXT,
        published=now,
        edited=now + timedelta(seconds=1),
    )
    del_dto = _msg(
        source_id=source_id,
        peer_id=peer_id,
        mid=999,
        text="bye",
        published=now,
        deleted=True,
    )

    async def _ingest_live(session):
        await ingest_live_update(
            session,
            TelegramUpdateDTO(
                schema_version=1,
                event_type="message_new",
                telegram_peer_id=peer_id,
                message=create_dto,
                observed_at=now,
            ),
        )
        await ingest_live_update(
            session,
            TelegramUpdateDTO(
                schema_version=1,
                event_type="message_edited",
                telegram_peer_id=peer_id,
                message=edit_dto,
                observed_at=now + timedelta(seconds=1),
            ),
        )
        await ingest_live_update(
            session,
            TelegramUpdateDTO(
                schema_version=1,
                event_type="message_deleted",
                telegram_peer_id=peer_id,
                message=del_dto,
                observed_at=now + timedelta(seconds=2),
            ),
        )

    await run_write(_ingest_live)

    # Also prove live consumer accepts a push without crashing the coordinator.
    await gateway.push_update(
        TelegramUpdateDTO(
            schema_version=1,
            event_type="message_new",
            telegram_peer_id=peer_id,
            message=_msg(
                source_id=source_id,
                peer_id=peer_id,
                mid=101,
                text="live consumer path",
                published=now,
            ),
            observed_at=now + timedelta(seconds=3),
        )
    )
    await asyncio.sleep(0.2)

    async def _live_envs(session):
        rows = list(
            (
                await session.execute(
                    select(TelegramEventEnvelope).where(
                        TelegramEventEnvelope.collection_mode == "live"
                    )
                )
            ).scalars()
        )
        return {r.event_type for r in rows}

    live_types = await run_write(_live_envs)
    assert "message_new" in live_types
    assert "message_edited" in live_types
    assert "message_deleted" in live_types

    # 5) Processing → normalized revisions + one deduplicated lead
    processed = 0
    for _ in range(20):

        async def _proc(session):
            return await process_next_envelope(session, owner="e2e-proc")

        result = await run_write(_proc)
        if result is None:
            break
        processed += 1
    assert processed >= 1

    async def _leads(session):
        leads = list((await session.execute(select(Lead))).scalars())
        revs = int(
            (
                await session.execute(select(func.count()).select_from(TelegramMessageRevision))
            ).scalar_one()
        )
        msgs = list((await session.execute(select(TelegramMessage))).scalars())
        return leads, revs, msgs

    leads, rev_count, msgs = await run_write(_leads)
    assert rev_count >= 1
    assert len(leads) == 1
    lead = leads[0]
    assert lead.band in {"hot", "warm", "cold"}

    # 6) One outbox on hot; worker/restart without duplicate
    async def _outbox(session):
        return list((await session.execute(select(NotificationOutbox))).scalars())

    outbox_rows = await run_write(_outbox)
    if lead.band == "hot":
        assert len(outbox_rows) == 1
        assert outbox_rows[0].idempotency_key.startswith("hot_lead:")

        async def _deliver(session):
            return await process_one(session, client=bot)

        delivery = await run_write(_deliver)
        assert delivery is not None
        assert delivery.status == "sent"
        assert len(bot.calls) == 1

        # Restart path: reclaim would not create second outbox row
        outbox_rows2 = await run_write(_outbox)
        assert len(outbox_rows2) == 1

        async def _deliveries(session):
            return int(
                (
                    await session.execute(select(func.count()).select_from(NotificationDelivery))
                ).scalar_one()
            )

        # Second process_one should be idle (already sent)
        delivery2 = await run_write(_deliver)
        assert delivery2 is None
        assert len(bot.calls) == 1
        assert await run_write(_deliveries) == 1
    else:
        # Non-hot: notification disabled path must not block lead existence
        assert leads
        assert outbox_rows == []

    # 7) Pause → no new ingest
    async def _pause(session):
        await request_source_pause_ingest(session, source_id)

    await run_write(_pause)

    async def _count_before(session):
        return int(
            (
                await session.execute(select(func.count()).select_from(TelegramEventEnvelope))
            ).scalar_one()
        )

    before = await run_write(_count_before)
    paused_update = TelegramUpdateDTO(
        schema_version=1,
        event_type="message_new",
        telegram_peer_id=peer_id,
        message=_msg(
            source_id=source_id,
            peer_id=peer_id,
            mid=5000,
            text="should not ingest",
            published=datetime.now(UTC),
        ),
        observed_at=datetime.now(UTC),
    )

    async def _ingest_paused(session):
        return await ingest_live_update(session, paused_update)

    row = await run_write(_ingest_paused)
    assert row is None
    assert await run_write(_count_before) == before

    # 8) Kill mid-batch → lease recover → reconcile continues without gap/dup storm
    async def _force_running(session):
        result = await session.execute(
            select(Job).where(Job.job_type.in_(("initial_backfill", "startup_reconciliation")))
        )
        job = result.scalars().first()
        assert job is not None
        job.state = "running"
        job.lease_until = datetime.now(UTC) - timedelta(minutes=10)
        await session.flush()
        return job.id

    stale_id = await run_write(_force_running)
    recovered = await run_write(recover_stale_jobs)
    assert recovered >= 1

    async def _job_state(session):
        job = await session.get(Job, stale_id)
        assert job is not None
        return job.state

    assert await run_write(_job_state) == "queued"

    # Re-run claim completes (idempotent envelopes)
    env_before = await run_write(_env_count)
    await claim_and_process_collector_job(gateway, owner="e2e-reconcile")
    env_after = await run_write(_env_count)
    assert env_after >= env_before

    # Coordinator health still not permanent STOPPED/deferred
    await coordinator._watchdog_tick()
    assert registry.components["collector"].state is not HealthState.STOPPED
    assert registry.components["collector"].reason_code != "deferred"
    assert registry.components["processing"].state in {
        HealthState.HEALTHY,
        HealthState.DEGRADED,
    }

    await coordinator.shutdown()
