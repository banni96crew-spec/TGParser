"""Integration — outbox idempotency (same key returns existing row)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from telegram_lead_discovery.infrastructure.paths import ensure_app_directories, resolve_app_paths
from telegram_lead_discovery.settings.service import seed_defaults, update_setting
from telegram_lead_discovery.storage.db import dispose_engine, init_engine
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import (
    Lead,
    NotificationOutbox,
    TelegramMessage,
    TelegramSource,
)
from telegram_lead_discovery.storage.outbox import enqueue_hot_lead, enqueue_outbox
from telegram_lead_discovery.storage.session import configure_session_factory, run_write


@pytest.fixture
async def db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("TG_BOT_TOKEN", "123456:ABCDEF-test-token-value")
    monkeypatch.setenv("TG_NOTIFY_CHAT_ID", "-100999")
    paths = ensure_app_directories(resolve_app_paths())
    upgrade_head(paths.database_path)
    engine = await init_engine(paths.database_path)
    configure_session_factory(engine)

    async def _seed(session):
        await seed_defaults(session)
        await update_setting(
            session,
            key="notifications.delivery_mode",
            typed_value="live",
            expected_settings_version=1,
            change_source="test",
        )
        source = TelegramSource(
            telegram_id=7,
            username_normalized="src",
            title="Src",
            source_type="channel",
            lifecycle_state="monitoring",
        )
        session.add(source)
        await session.flush()
        msg = TelegramMessage(
            source_id=source.id,
            telegram_message_id=1,
            published_at=datetime.now(UTC),
            original_text="x",
            normalized_text="x",
            normalized_hash="a" * 64,
            is_canonical=True,
        )
        session.add(msg)
        await session.flush()
        lead = Lead(
            canonical_message_id=msg.id,
            category="direct_order",
            band="hot",
            status="new",
        )
        session.add(lead)
        await session.flush()
        return lead.id

    lead_id = await run_write(_seed)
    yield paths, lead_id
    await dispose_engine()


@pytest.mark.asyncio
async def test_outbox_idempotency_same_key(db_env) -> None:
    _paths, lead_id = db_env

    async def _twice(session):
        first = await enqueue_hot_lead(session, lead_id=lead_id, score_version=1)
        second = await enqueue_hot_lead(session, lead_id=lead_id, score_version=1)
        rows = list((await session.execute(select(NotificationOutbox))).scalars())
        return first, second, rows

    first, second, rows = await run_write(_twice)
    assert first is not None
    assert second is not None
    assert first.id == second.id
    assert len(rows) == 1
    assert rows[0].idempotency_key == f"hot_lead:{lead_id}:1"


@pytest.mark.asyncio
async def test_shadow_skips_insert(db_env) -> None:
    _paths, lead_id = db_env

    async def _shadow(session):
        return await enqueue_outbox(
            session,
            event_type="hot_lead",
            idempotency_key=f"hot_lead:{lead_id}:99",
            lead_id=lead_id,
            score_version=99,
            delivery_mode="shadow",
        )

    result = await run_write(_shadow)
    assert result.inserted is False
    assert result.skipped_reason == "shadow_or_missing_secrets"
