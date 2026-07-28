"""Deterministic preliminary ranking for keyword discovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from telegram_lead_discovery.collector.ports import SourceSnapshot
from telegram_lead_discovery.source_discovery.evidence import (
    DiscoveryChannel,
    EvidenceRecord,
    _channel_sort_key,
)
from telegram_lead_discovery.source_discovery.identity import (
    DismissedKeywordSourceIndex,
    PresentedKeywordSourceIndex,
    SourceRegistryIndex,
    _ensure_utc,
    dismissed_telegram_ids,
    presented_telegram_ids,
    registry_telegram_ids,
)

MAX_DEEP_VERIFICATION_SOURCES = 25


@dataclass(frozen=True, slots=True)
class PreliminarySourceCandidate:
    """Seed-phase candidate for deep-verification selection (phase G)."""

    telegram_id: int
    source_type: str
    title: str
    username: str | None
    distinct_query_count: int
    seed_evidence_count: int
    directory_title_match: bool
    is_linked_discussion: bool
    freshest_evidence_at: datetime | None
    discovery_channels: tuple[DiscoveryChannel, ...]


def preliminary_rank_key(candidate: PreliminarySourceCandidate) -> tuple:
    """Phase G ranking: queries, evidence, directory, type, linked, freshness, id."""
    type_rank = {
        "megagroup": 0,
        "group": 1,
        "channel": 2,
    }.get(candidate.source_type, 3)
    linked_rank = 0 if candidate.is_linked_discussion else 1
    directory_rank = 0 if candidate.directory_title_match else 1
    fresh = (
        -_ensure_utc(candidate.freshest_evidence_at).timestamp()
        if candidate.freshest_evidence_at is not None
        else float("inf")
    )
    return (
        -candidate.distinct_query_count,
        -candidate.seed_evidence_count,
        directory_rank,
        type_rank,
        linked_rank,
        fresh,
        candidate.telegram_id,
    )


def select_sources_for_deep_verification(
    candidates: Sequence[PreliminarySourceCandidate],
    *,
    limit: int = MAX_DEEP_VERIFICATION_SOURCES,
) -> list[PreliminarySourceCandidate]:
    ordered = sorted(candidates, key=preliminary_rank_key)
    return ordered[: max(0, limit)]


def build_preliminary_candidates(
    evidence: Sequence[EvidenceRecord],
    *,
    directory_sources: Sequence[SourceSnapshot] = (),
    directory_query_texts: Sequence[str] = (),
    linked_parent_ids: Mapping[int, int] | None = None,
    registry: SourceRegistryIndex | None = None,
    dismissed: DismissedKeywordSourceIndex | None = None,
    presented: PresentedKeywordSourceIndex | None = None,
) -> list[PreliminarySourceCandidate]:
    """Derive phase-G candidates from seed evidence + directory hits."""
    suppressed = set(registry_telegram_ids(registry)) if registry is not None else set()
    if dismissed is not None:
        suppressed.update(dismissed_telegram_ids(dismissed))
    if presented is not None:
        suppressed.update(presented_telegram_ids(presented))
    by_source: dict[int, list[EvidenceRecord]] = {}
    for row in evidence:
        if row.source_telegram_id in suppressed:
            continue
        by_source.setdefault(row.source_telegram_id, []).append(row)

    directory_by_id = {s.telegram_id: s for s in directory_sources}
    query_folded = tuple(q.casefold() for q in directory_query_texts)
    parents = linked_parent_ids or {}

    candidates: dict[int, PreliminarySourceCandidate] = {}
    for telegram_id, rows in by_source.items():
        ordinals = {o for r in rows for o in r.matched_query_ordinals}
        channel_set = {c for r in rows for c in r.discovery_channels}
        channels: tuple[DiscoveryChannel, ...] = tuple(sorted(channel_set, key=_channel_sort_key))
        freshest = max(r.published_at for r in rows)
        meta = rows[0]
        title = meta.source_title
        dir_match = _directory_title_match(title, query_folded)
        if telegram_id in directory_by_id:
            dir_match = dir_match or _directory_title_match(
                directory_by_id[telegram_id].title, query_folded
            )
        candidates[telegram_id] = PreliminarySourceCandidate(
            telegram_id=telegram_id,
            source_type=meta.source_type,
            title=title,
            username=meta.source_username,
            distinct_query_count=len(ordinals),
            seed_evidence_count=len(rows),
            directory_title_match=dir_match,
            is_linked_discussion=telegram_id in parents,
            freshest_evidence_at=freshest,
            discovery_channels=channels,
        )

    for snap in directory_sources:
        if snap.telegram_id in suppressed:
            continue
        if snap.telegram_id in candidates:
            continue
        dir_match = _directory_title_match(snap.title, query_folded)
        candidates[snap.telegram_id] = PreliminarySourceCandidate(
            telegram_id=snap.telegram_id,
            source_type=snap.source_type,
            title=snap.title,
            username=snap.username,
            distinct_query_count=0,
            seed_evidence_count=0,
            directory_title_match=dir_match,
            is_linked_discussion=snap.telegram_id in parents,
            freshest_evidence_at=None,
            discovery_channels=("directory",),
        )
    return list(candidates.values())


def _directory_title_match(title: str, queries_folded: Sequence[str]) -> bool:
    folded = title.casefold()
    return any(q and q in folded for q in queries_folded)



__all__ = [
    "MAX_DEEP_VERIFICATION_SOURCES",
    "PreliminarySourceCandidate",
    "build_preliminary_candidates",
    "preliminary_rank_key",
    "select_sources_for_deep_verification",
]

