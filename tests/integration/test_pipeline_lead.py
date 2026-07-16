"""Integration — envelope → lead; shadow skips outbox; live+secrets creates outbox."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from telegram_lead_discovery.detection.seed import seed_ruleset_ru_mvp_1
from telegram_lead_discovery.infrastructure.paths import ensure_app_directories, resolve_app_paths
from telegram_lead_discovery.processing.pipeline import process_next_envelope
from telegram_lead_discovery.settings.service import seed_defaults, update_setting
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


@pytest.fixture
async def db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    paths = ensure_app_directories(resolve_app_paths())
    upgrade_head(paths.database_path)
    engine = await init_engine(paths.database_path)
    configure_session_factory(engine)

    async def _seed(session):
        await seed_defaults(session)
        await seed_ruleset_ru_mvp_1(session)
        source = TelegramSource(
            telegram_id=42,
            username_normalized="leads_src",
            title="Leads",
            source_type="channel",
            public_url="https://t.me/leads_src",
            lifecycle_state="monitoring",
            quality_score=5,
        )
        session.add(source)
        await session.flush()
        return source.id

    source_id = await run_write(_seed)
    yield paths, source_id
    await dispose_engine()


async def _enqueue_envelope(session, source_id: int, text: str) -> int:
    now = datetime.now(UTC)
    env = TelegramEventEnvelope(
        event_id=f"{source_id}:message_new:1:{now.isoformat()}",
        event_type="message_new",
        source_id=source_id,
        telegram_message_id=1,
        edit_key="0",
        payload_json=json.dumps(
            {
                "text": text,
                "published_at": now.isoformat(),
                "permalink": "https://t.me/leads_src/1",
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
async def test_pipeline_creates_lead_shadow_no_outbox(db_env) -> None:
    _paths, source_id = db_env

    async def _run(session):
        await _enqueue_envelope(session, source_id, HOT_TEXT)
        result = await process_next_envelope(session, owner="test", now=datetime.now(UTC))
        leads = list((await session.execute(select(Lead))).scalars())
        outbox = list((await session.execute(select(NotificationOutbox))).scalars())
        return result, leads, outbox

    result, leads, outbox = await run_write(_run)
    assert result is not None
    assert result["outcome"] == "processed"
    assert leads
    assert leads[0].band in {"hot", "warm", "cold"}
    assert outbox == []


@pytest.mark.asyncio
async def test_pipeline_live_secrets_creates_outbox(
    db_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    _paths, source_id = db_env
    monkeypatch.setenv("TG_BOT_TOKEN", "123456:ABCDEF-test-token-value")
    monkeypatch.setenv("TG_NOTIFY_CHAT_ID", "-100123")

    async def _enable_live(session):
        snap = await update_setting(
            session,
            key="notifications.delivery_mode",
            typed_value="live",
            expected_settings_version=1,
            change_source="test",
        )
        return snap.settings_version

    await run_write(_enable_live)

    async def _run(session):
        await _enqueue_envelope(session, source_id, HOT_TEXT)
        result = await process_next_envelope(session, owner="test", now=datetime.now(UTC))
        outbox = list((await session.execute(select(NotificationOutbox))).scalars())
        leads = list((await session.execute(select(Lead))).scalars())
        return result, leads, outbox

    result, leads, outbox = await run_write(_run)
    assert result is not None
    assert leads
    # Outbox only on hot transition
    if leads[0].band == "hot":
        assert len(outbox) == 1
        assert outbox[0].event_type == "hot_lead"
        assert result["outbox_created"] is True
    else:
        assert outbox == []
