"""Integration — Phase 4 shadow E2E: process, dedupe, no outbox/Bot API, lease recovery."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from telegram_lead_discovery.detection.seed import seed_ruleset_ru_mvp_1
from telegram_lead_discovery.infrastructure.paths import ensure_app_directories, resolve_app_paths
from telegram_lead_discovery.notifications.worker import deliver_one
from telegram_lead_discovery.processing.pipeline import claim_envelope, process_next_envelope
from telegram_lead_discovery.settings.service import get_setting, seed_defaults
from telegram_lead_discovery.storage.db import dispose_engine, init_engine
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import (
    Lead,
    NotificationOutbox,
    TelegramEventEnvelope,
    TelegramSource,
)
from telegram_lead_discovery.storage.session import configure_session_factory, run_write

HOT_TEXT = (
    "Нужно разработать интернет-магазин с оплатой и корзиной, "
    "бюджет 250000 ₽, срочно, готов начать, пишите @leadclient12."
)


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def post(self, url: str, *, json: dict | None = None):
        self.calls.append({"url": url, "json": json})
        raise AssertionError("Bot API must not be called in shadow mode")


@pytest.fixture
async def shadow_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("TG_BOT_TOKEN", "123456:SHADOW-TEST-TOKEN")
    monkeypatch.setenv("TG_NOTIFY_CHAT_ID", "-100999")
    paths = ensure_app_directories(resolve_app_paths())
    upgrade_head(paths.database_path)
    engine = await init_engine(paths.database_path)
    configure_session_factory(engine)

    async def _seed(session):
        await seed_defaults(session)
        await seed_ruleset_ru_mvp_1(session)
        assert await get_setting(session, "notifications.delivery_mode") == "shadow"
        source = TelegramSource(
            telegram_id=99,
            username_normalized="shadow_src",
            title="Shadow Src",
            source_type="channel",
            public_url="https://t.me/shadow_src",
            lifecycle_state="monitoring",
            quality_score=5,
        )
        session.add(source)
        await session.flush()
        return source.id

    source_id = await run_write(_seed)
    yield paths, source_id
    await dispose_engine()


async def _enqueue(
    session,
    source_id: int,
    *,
    telegram_message_id: int,
    text: str,
    received_at: datetime | None = None,
) -> int:
    now = received_at or datetime.now(UTC)
    env = TelegramEventEnvelope(
        event_id=f"{source_id}:message_new:{telegram_message_id}:{now.isoformat()}",
        event_type="message_new",
        source_id=source_id,
        telegram_message_id=telegram_message_id,
        edit_key="0",
        payload_json=json.dumps(
            {
                "text": text,
                "published_at": now.isoformat(),
                "permalink": f"https://t.me/shadow_src/{telegram_message_id}",
            },
            ensure_ascii=False,
        ),
        collection_mode="live",
        received_at=now,
        processing_state="queued",
    )
    session.add(env)
    await session.flush()
    return env.id


@pytest.mark.asyncio
async def test_shadow_e2e_process_dedupe_no_outbox_recovery(shadow_env) -> None:
    _paths, source_id = shadow_env
    client = RecordingClient()

    started = time.perf_counter()

    async def _process_first(session):
        await _enqueue(session, source_id, telegram_message_id=1, text=HOT_TEXT)
        result = await process_next_envelope(session, owner="shadow-e2e", now=datetime.now(UTC))
        leads = list((await session.execute(select(Lead))).scalars())
        outbox = list((await session.execute(select(NotificationOutbox))).scalars())
        return result, leads, outbox

    result, leads, outbox = await run_write(_process_first)
    elapsed = time.perf_counter() - started
    assert result is not None
    assert result["outcome"] == "processed"
    assert len(leads) == 1
    lead_id = leads[0].id
    assert outbox == []
    assert elapsed <= 10.0, f"process latency {elapsed:.3f}s exceeds 10s budget"

    async def _repost(session):
        await _enqueue(
            session,
            source_id,
            telegram_message_id=2,
            text=HOT_TEXT,
            received_at=datetime.now(UTC) + timedelta(seconds=1),
        )
        result2 = await process_next_envelope(session, owner="shadow-e2e", now=datetime.now(UTC))
        lead_count = (await session.execute(select(func.count()).select_from(Lead))).scalar_one()
        outbox2 = list((await session.execute(select(NotificationOutbox))).scalars())
        return result2, lead_count, outbox2

    result2, lead_count, outbox2 = await run_write(_repost)
    assert result2 is not None
    assert result2["outcome"] == "duplicate_suppressed"
    assert lead_count == 1
    assert outbox2 == []

    async def _deliver(session):
        return await deliver_one(session, client=client, now=datetime.now(UTC))

    delivered = await run_write(_deliver)
    assert not delivered
    assert client.calls == []

    async def _claim_and_abandon(session):
        await _enqueue(
            session,
            source_id,
            telegram_message_id=3,
            text=(
                "Ищу разработку лендинга под ключ, бюджет 80000, "
                "нужен срочно, пишите @recoverclient."
            ),
            received_at=datetime.now(UTC) + timedelta(seconds=2),
        )
        claimed = await claim_envelope(
            session, owner="crashed-worker", now=datetime.now(UTC)
        )
        assert claimed is not None
        assert claimed.processing_state == "processing"
        claimed.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        await session.flush()
        return claimed.id

    env_id = await run_write(_claim_and_abandon)

    async def _recover_and_process(session):
        before = (await session.execute(select(func.count()).select_from(Lead))).scalar_one()
        recovered = await process_next_envelope(
            session, owner="recover-worker", now=datetime.now(UTC)
        )
        after = (await session.execute(select(func.count()).select_from(Lead))).scalar_one()
        env = await session.get(TelegramEventEnvelope, env_id)
        outbox3 = list((await session.execute(select(NotificationOutbox))).scalars())
        return before, recovered, after, env.processing_state if env else None, outbox3

    before, recovered, after, state, outbox3 = await run_write(_recover_and_process)
    assert recovered is not None
    assert state == "acked"
    assert after - before <= 1
    assert outbox3 == []
    async def _original(session):
        return await session.get(Lead, lead_id)

    assert await run_write(_original) is not None
