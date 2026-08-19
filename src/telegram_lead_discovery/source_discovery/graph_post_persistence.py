"""Atomic persistence for graph-history responses."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.collector.ports import TelegramMessageDTO
from telegram_lead_discovery.source_discovery.active_chat import (
    source_scoped_author_key,
)
from telegram_lead_discovery.storage.models import (
    GraphDiscoveryPost,
    SourceDiscoveryEvent,
)

_WRITE_BATCH_SIZE = 50


async def persist_graph_posts(
    session: AsyncSession,
    *,
    run_id: int,
    source_id: int | None,
    source_telegram_id: int,
    source_username: str | None,
    request_ordinal: int,
    messages: Sequence[TelegramMessageDTO],
) -> int:
    """Stage every received post in the caller's cursor transaction."""
    parent_source_id = await _load_parent_source_id(session, run_id, source_id)
    now = datetime.now(UTC)
    values = [
        _post_values(
            run_id=run_id,
            source_id=source_id,
            parent_source_id=parent_source_id,
            source_telegram_id=source_telegram_id,
            source_username=source_username,
            request_ordinal=request_ordinal,
            message=message,
            created_at=now,
        )
        for message in messages
    ]
    for offset in range(0, len(values), _WRITE_BATCH_SIZE):
        statement = sqlite_insert(GraphDiscoveryPost).values(
            values[offset : offset + _WRITE_BATCH_SIZE]
        )
        statement = statement.on_conflict_do_nothing(
            index_elements=["run_id", "source_telegram_id", "telegram_message_id"]
        )
        await session.execute(statement)
    return len(values)


async def _load_parent_source_id(
    session: AsyncSession,
    run_id: int,
    source_id: int | None,
) -> int | None:
    if source_id is None:
        return None
    result = await session.execute(
        select(SourceDiscoveryEvent.parent_source_id)
        .where(
            SourceDiscoveryEvent.run_id == run_id,
            SourceDiscoveryEvent.source_id == source_id,
        )
        .order_by(SourceDiscoveryEvent.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _post_values(
    *,
    run_id: int,
    source_id: int | None,
    parent_source_id: int | None,
    source_telegram_id: int,
    source_username: str | None,
    request_ordinal: int,
    message: TelegramMessageDTO,
    created_at: datetime,
) -> dict[str, object | None]:
    author_key = None
    if message.author_kind == "user" and message.author_peer_id is not None:
        author_key = source_scoped_author_key(
            source_telegram_id,
            message.author_peer_id,
        )
    username = (source_username or "").lstrip("@").casefold() or None
    return {
        "run_id": run_id,
        "source_id": source_id,
        "parent_source_id": parent_source_id,
        "source_telegram_id": source_telegram_id,
        "source_username": username,
        "source_url": f"https://t.me/{username}" if username else None,
        "request_ordinal": request_ordinal,
        "telegram_message_id": message.telegram_message_id,
        "published_at": message.published_at,
        "message_text": message.text,
        "author_key": author_key,
        "author_kind": message.author_kind,
        "permalink": message.permalink,
        "created_at": created_at,
    }


__all__ = ["persist_graph_posts"]
