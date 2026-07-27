"""Storage helpers for durable dismiss suppress ledger (STO-017 / SRC-033..036).

Physical table ownership is STO. Logical identity/reconsider command ownership
remains SRC; source_discovery may wrap these helpers.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.storage.models import (
    DismissedKeywordSource,
    DismissSuppressReconsideredEvent,
)


def peer_canonical_key(telegram_id: int) -> str:
    return f"peer:{int(telegram_id)}"


def username_canonical_key(username: str) -> str:
    return f"username:{_normalize_username(username) or ''}"


def provisional_username_key(username: str) -> str:
    """Provisional identity key until Telegram peer resolve (SRC-034)."""
    normalized = _normalize_username(username)
    if not normalized:
        raise ValueError("provisional_username_required")
    return f"username:{normalized}"


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


@dataclass(frozen=True, slots=True)
class SuppressIdentity:
    canonical_key: str
    telegram_id: int | None = None
    username_normalized: str | None = None


@dataclass(frozen=True, slots=True)
class ReconsiderSuppressResult:
    removed: bool
    suppress_id: int | None
    canonical_key: str | None
    event_id: str | None


async def get_suppress_by_canonical_key(
    session: AsyncSession,
    *,
    canonical_key: str,
) -> DismissedKeywordSource | None:
    result = await session.execute(
        select(DismissedKeywordSource).where(
            DismissedKeywordSource.canonical_key == canonical_key
        )
    )
    return result.scalar_one_or_none()


async def upsert_dismiss_suppress(
    session: AsyncSession,
    *,
    identity: SuppressIdentity,
    reason: str,
    operator_trigger: str | None = None,
    origin_run_id: int | None = None,
    origin_opportunity_id: int | None = None,
    extra_aliases: tuple[str, ...] | list[str] | None = None,
) -> DismissedKeywordSource:
    """Insert or merge claim fields for one canonical suppress membership."""
    now = datetime.now(UTC)
    key = identity.canonical_key
    normalized = _normalize_username(identity.username_normalized)
    tid = identity.telegram_id

    existing = await session.execute(
        select(DismissedKeywordSource).where(
            DismissedKeywordSource.canonical_key == key
        )
    )
    row = existing.scalar_one_or_none()
    if row is None and tid is not None:
        by_tid = await session.execute(
            select(DismissedKeywordSource).where(
                DismissedKeywordSource.source_telegram_id == tid
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
        row = DismissedKeywordSource(
            canonical_key=key,
            source_telegram_id=tid,
            username_normalized=normalized,
            aliases_json=_dump_aliases(alias_set),
            dismiss_reason=reason,
            origin_run_id=origin_run_id,
            origin_opportunity_id=origin_opportunity_id,
            operator_trigger=operator_trigger,
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
    row.dismiss_reason = row.dismiss_reason or reason
    row.origin_run_id = row.origin_run_id or origin_run_id
    row.origin_opportunity_id = row.origin_opportunity_id or origin_opportunity_id
    if operator_trigger and not row.operator_trigger:
        row.operator_trigger = operator_trigger
    row.aliases_json = _dump_aliases(aliases)
    row.updated_at = now
    row.version = int(row.version or 1) + 1
    await session.flush()
    return row


async def merge_provisional_into_peer(
    session: AsyncSession,
    *,
    provisional_key: str,
    peer_telegram_id: int,
    aliases: tuple[str, ...] | list[str] | None = None,
) -> DismissedKeywordSource:
    """Atomically merge username:<casefold> suppress into peer:<id> (SRC-034)."""
    now = datetime.now(UTC)
    peer_key = peer_canonical_key(peer_telegram_id)
    provisional = await get_suppress_by_canonical_key(
        session, canonical_key=provisional_key
    )
    peer_row = await get_suppress_by_canonical_key(session, canonical_key=peer_key)
    if peer_row is None:
        by_tid = await session.execute(
            select(DismissedKeywordSource).where(
                DismissedKeywordSource.source_telegram_id == peer_telegram_id
            )
        )
        peer_row = by_tid.scalar_one_or_none()

    alias_set: set[str] = set()
    for item in aliases or ():
        n = _normalize_username(item)
        if n:
            alias_set.add(n)
    if provisional_key.startswith("username:"):
        alias_set.add(provisional_key.split(":", 1)[1])

    if provisional is None and peer_row is None:
        raise LookupError(f"suppress_not_found:{provisional_key}")

    if provisional is not None:
        alias_set |= set(_load_aliases(provisional.aliases_json))
        if provisional.username_normalized:
            alias_set.add(provisional.username_normalized)

    if peer_row is None:
        assert provisional is not None
        provisional.canonical_key = peer_key
        provisional.source_telegram_id = peer_telegram_id
        if provisional.username_normalized:
            alias_set.discard(provisional.username_normalized)
        provisional.aliases_json = _dump_aliases(alias_set)
        provisional.updated_at = now
        provisional.version = int(provisional.version or 1) + 1
        await session.flush()
        return provisional

    # Merge provisional claim fields into peer, then drop provisional row if distinct.
    alias_set |= set(_load_aliases(peer_row.aliases_json))
    if peer_row.username_normalized:
        alias_set.discard(peer_row.username_normalized)
    elif alias_set:
        primary = sorted(alias_set)[0]
        peer_row.username_normalized = primary
        alias_set.discard(primary)

    peer_row.canonical_key = peer_key
    peer_row.source_telegram_id = peer_telegram_id
    peer_row.aliases_json = _dump_aliases(alias_set)
    if provisional is not None:
        peer_row.dismiss_reason = peer_row.dismiss_reason or provisional.dismiss_reason
        peer_row.origin_run_id = peer_row.origin_run_id or provisional.origin_run_id
        peer_row.origin_opportunity_id = (
            peer_row.origin_opportunity_id or provisional.origin_opportunity_id
        )
        peer_row.operator_trigger = (
            peer_row.operator_trigger or provisional.operator_trigger
        )
        if provisional.id != peer_row.id:
            await session.delete(provisional)
    peer_row.updated_at = now
    peer_row.version = int(peer_row.version or 1) + 1
    await session.flush()
    return peer_row


async def reconsider_dismiss_suppress(
    session: AsyncSession,
    *,
    suppress_id: int | None = None,
    canonical_key: str | None = None,
    note: str = "",
    version: int | None = None,
) -> ReconsiderSuppressResult:
    """Remove suppress membership and append authoritative reconsider audit."""
    if suppress_id is None and not canonical_key:
        raise ValueError("suppress_id_or_canonical_key_required")

    row: DismissedKeywordSource | None = None
    if suppress_id is not None:
        row = await session.get(DismissedKeywordSource, suppress_id)
    if row is None and canonical_key:
        row = await get_suppress_by_canonical_key(session, canonical_key=canonical_key)
    if row is None:
        return ReconsiderSuppressResult(
            removed=False,
            suppress_id=suppress_id,
            canonical_key=canonical_key,
            event_id=None,
        )

    if version is not None and int(row.version or 1) != int(version):
        raise ValueError(
            f"suppress_version_conflict:expected={version},current={row.version}"
        )

    removed_id = row.id
    removed_key = row.canonical_key
    await session.delete(row)
    event_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    session.add(
        DismissSuppressReconsideredEvent(
            event_id=event_id,
            canonical_key=removed_key,
            suppress_id=removed_id,
            note=note or "",
            occurred_at=now,
            created_at=now,
        )
    )
    await session.flush()
    return ReconsiderSuppressResult(
        removed=True,
        suppress_id=removed_id,
        canonical_key=removed_key,
        event_id=event_id,
    )


__all__ = [
    "ReconsiderSuppressResult",
    "SuppressIdentity",
    "get_suppress_by_canonical_key",
    "merge_provisional_into_peer",
    "peer_canonical_key",
    "provisional_username_key",
    "reconsider_dismiss_suppress",
    "upsert_dismiss_suppress",
    "username_canonical_key",
]
