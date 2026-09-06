"""Deterministic preliminary admission for deep source verification."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

from telegram_lead_discovery.collector.ports import SourceSnapshot
from telegram_lead_discovery.source_discovery.evidence import EvidenceRecord
from telegram_lead_discovery.source_discovery.identity import (
    DismissedKeywordSourceIndex,
    PresentedKeywordSourceIndex,
    SourceRegistryIndex,
    dismissed_telegram_ids,
    presented_telegram_ids,
    registry_telegram_ids,
)
from telegram_lead_discovery.source_discovery.ranking_select import (
    select_preliminary_candidates,
    select_sources_for_deep_verification,
)
from telegram_lead_discovery.source_discovery.ranking_types import (
    DIVERSITY_RESERVATIONS,
    MAX_DEEP_VERIFICATION_SOURCES,
    SEARCH_DISCOVERY_CHANNELS,
    STRONG_BUYER_CATEGORIES,
    PreliminarySourceCandidate,
    diversity_reservations_for_profile,
    preliminary_rank_key,
    selected_lane,
)


def build_preliminary_candidates(
    evidence: Sequence[EvidenceRecord],
    *,
    directory_sources: Sequence[SourceSnapshot] = (),
    operator_seed_sources: Sequence[SourceSnapshot] = (),
    directory_query_texts: Sequence[str] = (),
    directory_candidate_ids: Collection[int] | None = None,
    linked_parent_ids: Mapping[int, int] | None = None,
    registry: SourceRegistryIndex | None = None,
    dismissed: DismissedKeywordSourceIndex | None = None,
    presented: PresentedKeywordSourceIndex | None = None,
) -> list[PreliminarySourceCandidate]:
    """Build eligible, deduplicated candidates from persisted scouting evidence."""
    suppressed = set(registry_telegram_ids(registry)) if registry is not None else set()
    if dismissed is not None:
        suppressed.update(dismissed_telegram_ids(dismissed))
    if presented is not None:
        suppressed.update(presented_telegram_ids(presented))

    parents = linked_parent_ids or {}
    directory_ids = (
        set(directory_candidate_ids)
        if directory_candidate_ids is not None
        else {snap.telegram_id for snap in directory_sources}
    )
    operator_seed_ids = {snap.telegram_id for snap in operator_seed_sources}
    snapshots = {snap.telegram_id: snap for snap in directory_sources}
    snapshots.update({snap.telegram_id: snap for snap in operator_seed_sources})
    by_source: dict[int, dict[int, EvidenceRecord]] = {}
    for row in evidence:
        if row.source_telegram_id in suppressed:
            continue
        if not any(channel != "source_verification" for channel in row.discovery_channels):
            continue
        by_source.setdefault(row.source_telegram_id, {}).setdefault(
            row.telegram_message_id, row
        )

    query_folded = tuple(query.casefold() for query in directory_query_texts)
    universe_ids = (set(by_source) | set(snapshots)) - suppressed
    candidates: list[PreliminarySourceCandidate] = []
    for telegram_id in sorted(universe_ids):
        rows = list(by_source.get(telegram_id, {}).values())
        snap = snapshots.get(telegram_id)
        first = rows[0] if rows else None
        source_type = first.source_type if first is not None else snap.source_type if snap else ""
        username = first.source_username if first is not None else snap.username if snap else None
        if source_type != "megagroup" or not username:
            continue
        title = (
            first.source_title
            if first is not None
            else snap.title
            if snap
            else str(telegram_id)
        )
        qualified = [row for row in rows if row.is_qualified]
        channels = {
            channel
            for row in rows
            for channel in row.discovery_channels
            if channel != "source_verification"
        }
        qualified_ordinals = {
            ordinal for row in qualified for ordinal in row.matched_query_ordinals
        }
        all_ordinals = {ordinal for row in rows for ordinal in row.matched_query_ordinals}
        freshest = max((row.published_at for row in rows), default=None)
        candidates.append(
            PreliminarySourceCandidate(
                telegram_id=telegram_id,
                source_type=source_type,
                title=title,
                username=username,
                raw_evidence_count=len(rows),
                qualified_evidence_count=len(qualified),
                qualified_distinct_query_count=len(qualified_ordinals),
                strong_buyer_intent_count=sum(
                    1
                    for row in qualified
                    if row.detection_category in STRONG_BUYER_CATEGORIES
                ),
                potential_need_count=sum(
                    1 for row in qualified if row.detection_category == "potential_need"
                ),
                hard_excluded_count=sum(1 for row in rows if row.hard_exclusion),
                freshest_seed_evidence_at=freshest,
                directory_title_match=(
                    _directory_title_match(title, query_folded)
                    or bool(snap and _directory_title_match(snap.title, query_folded))
                ),
                is_search_candidate=bool(SEARCH_DISCOVERY_CHANNELS.intersection(channels)),
                is_directory_candidate=telegram_id in directory_ids,
                is_operator_seed_candidate=telegram_id in operator_seed_ids,
                is_linked_discussion=telegram_id in parents,
                linked_parent_telegram_id=parents.get(telegram_id),
                discovery_channels=tuple(sorted(channels)),  # type: ignore[arg-type]
                distinct_query_count=len(all_ordinals),
                seed_evidence_count=len(rows),
                freshest_evidence_at=freshest,
            )
        )
    return candidates


def _directory_title_match(title: str, queries_folded: Sequence[str]) -> bool:
    folded = title.casefold()
    return any(query and query in folded for query in queries_folded)


__all__ = [
    "DIVERSITY_RESERVATIONS",
    "MAX_DEEP_VERIFICATION_SOURCES",
    "PreliminarySourceCandidate",
    "build_preliminary_candidates",
    "diversity_reservations_for_profile",
    "preliminary_rank_key",
    "select_preliminary_candidates",
    "select_sources_for_deep_verification",
    "selected_lane",
]
