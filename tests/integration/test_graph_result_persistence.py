from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from telegram_lead_discovery.collector.fake import FakeTelegramGateway, make_source
from telegram_lead_discovery.collector.ports import TelegramMessageDTO
from telegram_lead_discovery.infrastructure.paths import database_path, ensure_directories
from telegram_lead_discovery.source_discovery.graph_discovery import (
    start_graph_discovery_run,
)
from telegram_lead_discovery.source_discovery.worker import (
    claim_and_process_graph_job,
)
from telegram_lead_discovery.storage.db import dispose_engine, init_engine, session_scope
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import (
    DiscoveryRun,
    GraphDiscoveryPost,
    TelegramSource,
)
from telegram_lead_discovery.storage.retention_graph import (
    clear_graph_post_texts,
    purge_graph_post_rows,
)


class _CommitProbeGateway(FakeTelegramGateway):
    def __init__(self, database: Path) -> None:
        super().__init__()
        self.database = database
        self.posts_visible_before_next_request = False

    async def get_recommendations(self, source, limit):
        if source.telegram_id == 200:
            with sqlite3.connect(self.database) as connection:
                count = connection.execute(
                    "SELECT count(*) FROM graph_discovery_posts "
                    "WHERE source_telegram_id=100"
                ).fetchone()[0]
            self.posts_visible_before_next_request = count == 2
        return await super().get_recommendations(source, limit)


@pytest.fixture
async def db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    ensure_directories()
    path = database_path()
    upgrade_head(path)
    await init_engine(path)
    yield path
    await dispose_engine()


@pytest.mark.asyncio
async def test_graph_posts_are_committed_before_next_telegram_request(db_env: Path) -> None:
    gateway = _CommitProbeGateway(db_env)
    child = make_source(telegram_id=200, username="child_source")
    gateway.set_recommendations(100, [child])
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    gateway.set_graph_sample_messages(
        100,
        [
            TelegramMessageDTO(
                schema_version=2,
                source_id=1,
                telegram_message_id=11,
                published_at=now,
                text="Нужно разработать сайт",
                telegram_peer_id=100,
                author_peer_id=501,
                author_kind="user",
                permalink="https://t.me/seed_source/11",
            ),
            TelegramMessageDTO(
                schema_version=2,
                source_id=1,
                telegram_message_id=12,
                published_at=now,
                text="Нужен Telegram-бот",
                telegram_peer_id=100,
                author_peer_id=502,
                author_kind="user",
                permalink="https://t.me/seed_source/12",
            ),
        ],
    )

    async with session_scope() as session:
        seed = TelegramSource(
            telegram_id=100,
            username_normalized="seed_source",
            title="Seed",
            source_type="channel",
            public_url="https://t.me/seed_source",
            lifecycle_state="monitoring",
            quality_score=0,
        )
        session.add(seed)
        await session.flush()
        started = await start_graph_discovery_run(session, seed_source_ids=[seed.id])
        run_id = started.run.id
        await session.commit()

    async with session_scope() as session:
        result = await claim_and_process_graph_job(session, gateway)
        await session.commit()

    assert result is not None
    assert result["outcome"] == "succeeded"
    assert gateway.posts_visible_before_next_request is True

    async with session_scope() as session:
        rows = list(
            (
                await session.execute(
                    select(GraphDiscoveryPost)
                    .where(GraphDiscoveryPost.run_id == run_id)
                    .order_by(GraphDiscoveryPost.telegram_message_id)
                )
            )
            .scalars()
            .all()
        )
        assert [row.message_text for row in rows] == [
            "Нужно разработать сайт",
            "Нужен Telegram-бот",
        ]
        assert len({row.author_key for row in rows}) == 2
        assert all(row.author_key and len(row.author_key) == 64 for row in rows)
        assert [row.permalink for row in rows] == [
            "https://t.me/seed_source/11",
            "https://t.me/seed_source/12",
        ]
        run = await session.get(DiscoveryRun, run_id)
        cursor = json.loads(run.cursor_json)
        stage = cursor["stage_results"]["peer:100"]["message_sample_100"]
        assert cursor["schema_version"] == 3
        assert stage["posts_persisted"] == 2
        assert stage["source_telegram_id"] == 100
        assert cursor["termination"]["reason"] == "completed"


@pytest.mark.asyncio
async def test_graph_post_retention_clears_text_then_deletes_row(db_env: Path) -> None:
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    async with session_scope() as session:
        run = DiscoveryRun(run_type="graph", state="succeeded", counters_json="{}")
        session.add(run)
        await session.flush()
        session.add_all(
            [
                GraphDiscoveryPost(
                    run_id=run.id,
                    source_telegram_id=100,
                    source_username="source",
                    source_url="https://t.me/source",
                    request_ordinal=1,
                    telegram_message_id=1,
                    published_at=now,
                    message_text="31 days",
                    author_kind="unknown",
                    permalink="https://t.me/source/1",
                    created_at=now - timedelta(days=31),
                ),
                GraphDiscoveryPost(
                    run_id=run.id,
                    source_telegram_id=100,
                    source_username="source",
                    source_url="https://t.me/source",
                    request_ordinal=1,
                    telegram_message_id=2,
                    published_at=now,
                    message_text="91 days",
                    author_kind="unknown",
                    permalink="https://t.me/source/2",
                    created_at=now - timedelta(days=91),
                ),
            ]
        )
        await session.commit()

    async with session_scope() as session:
        assert await clear_graph_post_texts(session, now=now) == 2
        assert await purge_graph_post_rows(session, now=now) == 1
        await session.commit()

    async with session_scope() as session:
        rows = list(
            (
                await session.execute(
                    select(GraphDiscoveryPost).order_by(GraphDiscoveryPost.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].telegram_message_id == 1
        assert rows[0].message_text == ""
