"""Manual source candidates and source listing."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.collector.ports import PublicSourceRef, TelegramGateway
from telegram_lead_discovery.source_discovery.normalization import normalize_username
from telegram_lead_discovery.storage.models import (
    DiscoveryRun,
    SourceDiscoveryEvent,
    TelegramSource,
)


async def add_manual_candidate(
    session: AsyncSession,
    *,
    username_or_url: str,
    gateway: TelegramGateway | None = None,
) -> tuple[TelegramSource, DiscoveryRun]:
    username = normalize_username(username_or_url)
    run = DiscoveryRun(
        root_source_ids_json="[]",
        max_depth=0,
        expansion_cap=0,
        candidate_cap=1,
        state="running",
        started_at=datetime.now(UTC),
    )
    session.add(run)
    await session.flush()

    existing = await session.execute(
        select(TelegramSource).where(TelegramSource.username_normalized == username)
    )
    source = existing.scalar_one_or_none()
    if source is None:
        title = username
        telegram_id = None
        source_type = "channel"
        public_url = f"https://t.me/{username}"
        if gateway is not None:
            # Do not hold a write transaction across Telegram resolve.
            await session.commit()
            snap = await gateway.resolve_public_source(
                PublicSourceRef(schema_version=1, username_or_url=username)
            )
            telegram_id = snap.telegram_id
            title = snap.title
            source_type = snap.source_type
            public_url = snap.public_url
        source = TelegramSource(
            telegram_id=telegram_id,
            username_normalized=username,
            title=title,
            source_type=source_type,
            public_url=public_url,
            lifecycle_state="candidate",
            quality_score=2,
        )
        session.add(source)
        await session.flush()

    run.root_source_ids_json = f"[{source.id}]"
    session.add(
        SourceDiscoveryEvent(
            event_id=str(uuid.uuid4()),
            run_id=run.id,
            source_id=source.id,
            method="manual",
            parent_source_id=None,
            raw_reference=username_or_url,
            normalized_reference=username,
            outcome="candidate",
            depth=0,
        )
    )
    run.state = "succeeded"
    run.finished_at = datetime.now(UTC)
    await session.flush()
    return source, run


async def list_sources(session: AsyncSession) -> list[TelegramSource]:
    result = await session.execute(select(TelegramSource).order_by(TelegramSource.id.asc()))
    return list(result.scalars().all())
