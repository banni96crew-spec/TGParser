from __future__ import annotations

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *

from telegram_lead_discovery.source_discovery.worker_parts.core import _WorkerContext, _utcnow


async def _load_registry(session: AsyncSession) -> SourceRegistryIndex:
    sources = list((await session.execute(select(TelegramSource))).scalars().all())
    aliases = list((await session.execute(select(SourceAlias))).scalars().all())
    alias_by_source: dict[int, list[str]] = {}
    for alias in aliases:
        alias_by_source.setdefault(alias.source_id, []).append(alias.normalized_username)
    entries = [
        RegistrySourceEntry(
            source_id=src.id,
            telegram_id=src.telegram_id,
            username_normalized=src.username_normalized,
            aliases=tuple(alias_by_source.get(src.id, ())),
        )
        for src in sources
    ]
    return SourceRegistryIndex.from_entries(entries)


async def _load_dismissed_sources(session: AsyncSession) -> DismissedKeywordSourceIndex:
    rows = list((await session.execute(select(DismissedKeywordSource))).scalars().all())
    entries: list[DismissedKeywordSourceEntry] = []
    for row in rows:
        aliases: tuple[str, ...]
        try:
            raw = json.loads(row.aliases_json or "[]")
            aliases = tuple(str(item) for item in raw if isinstance(item, str))
        except json.JSONDecodeError:
            aliases = ()
        entries.append(
            DismissedKeywordSourceEntry(
                telegram_id=row.source_telegram_id,
                username_normalized=row.username_normalized,
                aliases=aliases,
            )
        )
    return DismissedKeywordSourceIndex.from_entries(entries)


async def _load_presented_sources(
    session: AsyncSession,
) -> PresentedKeywordSourceIndex:
    """Load durable already-shown suppress ledger (SRC-041 / D-069)."""
    rows = list((await session.execute(select(PresentedKeywordSource))).scalars().all())
    entries: list[PresentedKeywordSourceEntry] = []
    for row in rows:
        if row.source_telegram_id is None:
            continue
        aliases: tuple[str, ...]
        try:
            raw = json.loads(row.aliases_json or "[]")
            aliases = tuple(str(item) for item in raw if isinstance(item, str))
        except json.JSONDecodeError:
            aliases = ()
        entries.append(
            PresentedKeywordSourceEntry(
                telegram_id=row.source_telegram_id,
                username_normalized=row.username_normalized,
                aliases=aliases,
            )
        )
    return PresentedKeywordSourceIndex.from_entries(entries)


def _dismissed_canonical_id(
    ctx: _WorkerContext, *, telegram_id: int, username: str | None
) -> int | None:
    match = resolve_dismissed_identity(
        telegram_id=telegram_id,
        username=username,
        dismissed=ctx.dismissed,
    )
    return None if match is None else match.canonical_telegram_id


def _presented_canonical_id(
    ctx: _WorkerContext, *, telegram_id: int, username: str | None
) -> int | None:
    match = resolve_presented_identity(
        telegram_id=telegram_id,
        username=username,
        presented=ctx.presented,
    )
    return None if match is None else match.canonical_telegram_id
