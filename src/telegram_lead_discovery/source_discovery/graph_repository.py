"""Database reads for graph discovery."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.collector.ports import SourceSnapshot
from telegram_lead_discovery.source_discovery.graph_policy import GraphQueueItem
from telegram_lead_discovery.source_discovery.identity import (
    RegistrySourceEntry,
    SourceRegistryIndex,
)
from telegram_lead_discovery.storage.models import (
    DiscoveryRun,
    SourceAlias,
    TelegramSource,
)

ACTIVE_GRAPH_RUN_STATES = frozenset({"queued", "running"})


async def find_active_graph_run(session: AsyncSession) -> DiscoveryRun | None:
    result = await session.execute(
        select(DiscoveryRun)
        .where(
            DiscoveryRun.run_type == "graph",
            DiscoveryRun.state.in_(tuple(ACTIVE_GRAPH_RUN_STATES)),
        )
        .order_by(DiscoveryRun.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def load_graph_seeds(
    session: AsyncSession, run: DiscoveryRun
) -> list[GraphQueueItem]:
    raw = json.loads(run.root_source_ids_json or "[]")
    if not isinstance(raw, list):
        return []
    items: list[GraphQueueItem] = []
    for source_id in raw:
        row = await session.get(TelegramSource, int(source_id))
        if row is None or row.telegram_id is None:
            continue
        items.append(
            GraphQueueItem(
                seed_telegram_id=int(row.telegram_id),
                seed_source_id=row.id,
                depth=0,
                username=row.username_normalized,
            )
        )
    # SRC-006: depth ASC, discovered_at ASC, normalized reference ASC.
    items.sort(key=lambda i: (i.depth, i.seed_telegram_id, i.username or ""))
    return items


async def _find_existing_source(
    session: AsyncSession, snap: SourceSnapshot
) -> TelegramSource | None:
    by_id = await session.execute(
        select(TelegramSource).where(TelegramSource.telegram_id == snap.telegram_id)
    )
    found = by_id.scalar_one_or_none()
    if found is not None:
        return found
    username = snap.username.lower()
    by_user = await session.execute(
        select(TelegramSource).where(TelegramSource.username_normalized == username)
    )
    found = by_user.scalar_one_or_none()
    if found is not None:
        return found
    alias = await session.execute(
        select(SourceAlias).where(SourceAlias.normalized_username == username)
    )
    alias_row = alias.scalar_one_or_none()
    if alias_row is not None:
        return await session.get(TelegramSource, alias_row.source_id)
    return None


async def load_registry_index(session: AsyncSession) -> SourceRegistryIndex:
    rows = list((await session.execute(select(TelegramSource))).scalars().all())
    aliases = list((await session.execute(select(SourceAlias))).scalars().all())
    alias_by_source: dict[int, list[str]] = {}
    for alias in aliases:
        alias_by_source.setdefault(alias.source_id, []).append(alias.normalized_username)
    entries = [
        RegistrySourceEntry(
            source_id=row.id,
            telegram_id=row.telegram_id,
            username_normalized=row.username_normalized,
            aliases=tuple(alias_by_source.get(row.id, ())),
        )
        for row in rows
    ]
    return SourceRegistryIndex.from_entries(entries)
