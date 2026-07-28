"""Storage helpers for durable presented-source suppress ledger (STO-020 / SRC-041/050).

Physical table ownership is STO. Logical already-shown suppress ownership remains SRC.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.storage.dismissed_suppress import (
    SuppressIdentity,
    peer_canonical_key,
    username_canonical_key,
)
from telegram_lead_discovery.storage.models import PresentedKeywordSource


def _normalize_username(username: str | None) -> str | None:
    if username is None:
        return None
    text = username.strip().lstrip("@").casefold()
    return text or None


def _load_aliases(raw: str | None) -> list[str]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in data if isinstance(item, str)]


def _dump_aliases(aliases: set[str] | list[str]) -> str:
    return json.dumps(sorted({a for a in aliases if a}), ensure_ascii=False)


async def get_presented_by_canonical_key(
    session: AsyncSession,
    *,
    canonical_key: str,
) -> PresentedKeywordSource | None:
    result = await session.execute(
        select(PresentedKeywordSource).where(
            PresentedKeywordSource.canonical_key == canonical_key
        )
    )
    return result.scalar_one_or_none()


async def upsert_presented_suppress(
    session: AsyncSession,
    *,
    identity: SuppressIdentity,
    origin_run_id: int | None = None,
    origin_opportunity_id: int | None = None,
    extra_aliases: tuple[str, ...] | list[str] | None = None,
    first_presented_at: datetime | None = None,
) -> PresentedKeywordSource:
    """Insert or merge claim fields for one already-shown suppress membership (idempotent)."""
    now = datetime.now(UTC)
    key = identity.canonical_key
    normalized = _normalize_username(identity.username_normalized)
    tid = identity.telegram_id

    existing = await session.execute(
        select(PresentedKeywordSource).where(PresentedKeywordSource.canonical_key == key)
    )
    row = existing.scalar_one_or_none()
    if row is None and tid is not None:
        by_tid = await session.execute(
            select(PresentedKeywordSource).where(
                PresentedKeywordSource.source_telegram_id == tid
            )
        )
        row = by_tid.scalar_one_or_none()

    alias_set: set[str] = set()
    for item in extra_aliases or ():
        n = _normalize_username(item)
        if n:
            alias_set.add(n)

    if row is None:
        if normalized:
            alias_set.discard(normalized)
        row = PresentedKeywordSource(
            canonical_key=key,
            source_telegram_id=tid,
            username_normalized=normalized,
            aliases_json=_dump_aliases(alias_set),
            origin_run_id=origin_run_id,
            origin_opportunity_id=origin_opportunity_id,
            first_presented_at=first_presented_at or now,
            version=1,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        return row

    aliases = set(_load_aliases(row.aliases_json)) | alias_set
    if normalized:
        if row.username_normalized is None:
            row.username_normalized = normalized
        elif normalized != row.username_normalized:
            aliases.add(normalized)
            if row.username_normalized:
                aliases.add(row.username_normalized)
        aliases.discard(row.username_normalized or "")
    if tid is not None:
        row.source_telegram_id = tid
        if not row.canonical_key.startswith("peer:"):
            row.canonical_key = peer_canonical_key(tid)
    elif not row.canonical_key:
        row.canonical_key = key
    row.origin_run_id = row.origin_run_id or origin_run_id
    row.origin_opportunity_id = row.origin_opportunity_id or origin_opportunity_id
    row.aliases_json = _dump_aliases(aliases)
    row.updated_at = now
    row.version = int(row.version or 1) + 1
    await session.flush()
    return row


__all__ = [
    "get_presented_by_canonical_key",
    "peer_canonical_key",
    "upsert_presented_suppress",
    "username_canonical_key",
]
