"""SQL query helpers for discovery presentation."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from telegram_lead_discovery.dashboard.discovery.view_models import _loads_json_obj
from telegram_lead_discovery.storage.dismissed_suppress import get_suppress_by_canonical_key
from telegram_lead_discovery.storage.models import (
    DismissedKeywordSource,
    SourceAlias,
    SourceOpportunitySnapshot,
    TelegramSource,
)


def _apply_band_filter(stmt: Any, band_mode: str) -> Any:
    if band_mode == "all" or band_mode == "default":
        return stmt
    if band_mode == "promising" or band_mode == "review" or band_mode == "weak":
        return stmt.where(SourceOpportunitySnapshot.band == band_mode)
    return stmt


async def _lifecycle_map(
    session: Any, rows: list[SourceOpportunitySnapshot]
) -> dict[int, str]:
    source_ids = {r.source_id for r in rows if r.source_id is not None}
    if not source_ids:
        return {}
    sources = (
        await session.execute(
            select(TelegramSource).where(TelegramSource.id.in_(source_ids))
        )
    ).scalars().all()
    return {s.id: s.lifecycle_state for s in sources}


async def _aliases_for_source(
    session: Any, source_id: int | None
) -> list[str]:
    if source_id is None:
        return []
    rows = (
        await session.execute(
            select(SourceAlias)
            .where(SourceAlias.source_id == source_id)
            .order_by(SourceAlias.id.asc())
        )
    ).scalars().all()
    return [r.normalized_username for r in rows]


async def _suppress_for_opportunity(
    session: Any, row: SourceOpportunitySnapshot
) -> dict[str, Any] | None:
    key = (
        f"peer:{row.source_telegram_id}"
        if row.source_telegram_id is not None
        else (
            f"username:{str(row.username).casefold()}" if row.username else None
        )
    )
    suppress_row: DismissedKeywordSource | None = None
    if key:
        suppress_row = await get_suppress_by_canonical_key(session, canonical_key=key)
    if suppress_row is None and row.source_telegram_id is not None:
        suppress_row = (
            await session.execute(
                select(DismissedKeywordSource).where(
                    DismissedKeywordSource.source_telegram_id == row.source_telegram_id
                )
            )
        ).scalar_one_or_none()
    if suppress_row is None:
        return None
    aliases = _loads_json_obj(suppress_row.aliases_json, [])
    if not isinstance(aliases, list):
        aliases = []
    return {
        "id": suppress_row.id,
        "canonical_key": suppress_row.canonical_key,
        "version": suppress_row.version,
        "dismiss_reason": suppress_row.dismiss_reason,
        "aliases": [str(a) for a in aliases],
    }
