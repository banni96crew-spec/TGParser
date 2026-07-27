"""Canonical source identity for dismiss suppress (SRC-033..036).

Logical ownership is Source Discovery. Physical ledger helpers live in
``storage.dismissed_suppress``; this module is the SRC-facing API.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.storage import dismissed_suppress as _sto
from telegram_lead_discovery.storage.models import DismissedKeywordSource


def peer_key(telegram_id: int) -> str:
    """Stable peer identity key ``peer:<telegram_id>``."""
    return _sto.peer_canonical_key(telegram_id)


def provisional_username_key(username: str) -> str:
    """Provisional identity until Telegram peer resolve (SRC-034)."""
    return _sto.provisional_username_key(username)


def _normalize_username(username: str | None) -> str | None:
    if username is None:
        return None
    text = username.strip().lstrip("@").casefold()
    return text or None


@dataclass(frozen=True, slots=True)
class CanonicalSourceIdentity:
    """SRC-owned canonical identity claim for suppress membership."""

    canonical_key: str
    telegram_id: int | None = None
    username_normalized: str | None = None
    aliases: tuple[str, ...] = ()


def collapse_identity_claims(
    claims: Sequence[CanonicalSourceIdentity],
    *,
    resolved_peer_id: int,
    aliases: Sequence[str] = (),
) -> CanonicalSourceIdentity:
    """Collapse rename/alias claims onto one peer:<id> identity (SRC-033)."""
    alias_set: set[str] = set()
    primary_username: str | None = None
    for claim in claims:
        if claim.username_normalized:
            normalized = _normalize_username(claim.username_normalized)
            if normalized:
                alias_set.add(normalized)
                if primary_username is None:
                    primary_username = normalized
        for item in claim.aliases:
            normalized = _normalize_username(item)
            if normalized:
                alias_set.add(normalized)
    for item in aliases:
        normalized = _normalize_username(item)
        if normalized:
            alias_set.add(normalized)
    return CanonicalSourceIdentity(
        canonical_key=peer_key(resolved_peer_id),
        telegram_id=int(resolved_peer_id),
        username_normalized=primary_username,
        aliases=tuple(sorted(alias_set)),
    )


def _row_to_identity(row: DismissedKeywordSource) -> CanonicalSourceIdentity:
    raw_aliases: Iterable[str]
    try:
        import json

        data = json.loads(row.aliases_json or "[]")
        raw_aliases = [str(item) for item in data if isinstance(item, str)]
    except (TypeError, ValueError):
        raw_aliases = ()
    return CanonicalSourceIdentity(
        canonical_key=row.canonical_key,
        telegram_id=row.source_telegram_id,
        username_normalized=row.username_normalized,
        aliases=tuple(raw_aliases),
    )


async def merge_provisional_into_peer(
    session: AsyncSession,
    *,
    provisional_key: str,
    peer_telegram_id: int,
    aliases: tuple[str, ...] | list[str] | None = None,
) -> CanonicalSourceIdentity:
    """Merge username:<casefold> suppress into peer:<id> (SRC-034)."""
    row = await _sto.merge_provisional_into_peer(
        session,
        provisional_key=provisional_key,
        peer_telegram_id=peer_telegram_id,
        aliases=aliases,
    )
    return _row_to_identity(row)


__all__ = [
    "CanonicalSourceIdentity",
    "collapse_identity_claims",
    "merge_provisional_into_peer",
    "peer_key",
    "provisional_username_key",
]
