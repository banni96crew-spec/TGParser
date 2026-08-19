"""Retention for durable graph-discovery post samples."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.storage.models import GraphDiscoveryPost
from telegram_lead_discovery.storage.retention_batches import purge_batches

BATCH_LIMIT = 500
GRAPH_POST_TEXT_RETENTION = timedelta(days=30)
GRAPH_POST_ROW_RETENTION = timedelta(days=90)


async def clear_graph_post_texts(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    retention: timedelta = GRAPH_POST_TEXT_RETENTION,
    batch_limit: int = BATCH_LIMIT,
) -> int:
    """Clear graph post text after 30 days; retain identity and link."""
    cutoff = (now or datetime.now(UTC)) - retention

    async def _once(session: AsyncSession, *, batch_limit: int) -> int:
        result = await session.execute(
            select(GraphDiscoveryPost.id)
            .where(
                GraphDiscoveryPost.created_at < cutoff,
                GraphDiscoveryPost.message_text != "",
            )
            .order_by(GraphDiscoveryPost.id.asc())
            .limit(batch_limit)
        )
        ids = list(result.scalars().all())
        if not ids:
            return 0
        updated = await session.execute(
            update(GraphDiscoveryPost)
            .where(GraphDiscoveryPost.id.in_(ids))
            .values(message_text="")
        )
        await session.flush()
        return int(updated.rowcount or 0)

    return await purge_batches(session, batch_limit=batch_limit, purge_once=_once)


async def purge_graph_post_rows(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    retention: timedelta = GRAPH_POST_ROW_RETENTION,
    batch_limit: int = BATCH_LIMIT,
) -> int:
    """Delete graph post metadata after 90 days."""
    cutoff = (now or datetime.now(UTC)) - retention

    async def _once(session: AsyncSession, *, batch_limit: int) -> int:
        result = await session.execute(
            select(GraphDiscoveryPost.id)
            .where(GraphDiscoveryPost.created_at < cutoff)
            .order_by(GraphDiscoveryPost.id.asc())
            .limit(batch_limit)
        )
        ids = list(result.scalars().all())
        if not ids:
            return 0
        deleted = await session.execute(
            delete(GraphDiscoveryPost).where(GraphDiscoveryPost.id.in_(ids))
        )
        await session.flush()
        return int(deleted.rowcount or 0)

    return await purge_batches(session, batch_limit=batch_limit, purge_once=_once)
