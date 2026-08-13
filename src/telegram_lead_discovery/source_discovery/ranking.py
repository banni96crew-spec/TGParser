"""Deterministic preliminary admission for deep source verification."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from telegram_lead_discovery.collector.ports import SourceSnapshot
from telegram_lead_discovery.source_discovery.evidence import DiscoveryChannel, EvidenceRecord
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
STRONG_BUYER_CATEGORIES = frozenset(
    {"direct_order", "contractor_search", "recommendation_request"}
)
SEARCH_DISCOVERY_CHANNELS = frozenset({"global_message", "public_posts"})
DIVERSITY_RESERVATIONS: Mapping[str, int] = {
    "LINKED_DISCUSSION": 3,
    "DIRECTORY": 3,
    "EXPLORATION": 1,
}


@dataclass(frozen=True, slots=True)
class PreliminarySourceCandidate:
    """Eligible immutable candidate with persisted-seed metrics and provenance."""

    telegram_id: int
    source_type: str
    title: str
    username: str | None
    raw_evidence_count: int | None = None
    qualified_evidence_count: int = 0
    qualified_distinct_query_count: int | None = None
    strong_buyer_intent_count: int = 0
    potential_need_count: int = 0
    hard_excluded_count: int = 0
    freshest_seed_evidence_at: datetime | None = None
    directory_title_match: bool = False
    is_search_candidate: bool | None = None
    is_directory_candidate: bool | None = None
    is_linked_discussion: bool = False
    linked_parent_telegram_id: int | None = None
    discovery_channels: tuple[DiscoveryChannel, ...] = ()
    selection_phase: str | None = None
    selected_lane: str | None = None
    selection_reason: str | None = None
    preliminary_position: int | None = None

    # Compatibility inputs/properties for callers of the pre-Cycle-1 contract.
    distinct_query_count: int = 0
    seed_evidence_count: int = 0
    freshest_evidence_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.raw_evidence_count is None:
            object.__setattr__(self, "raw_evidence_count", self.seed_evidence_count)
        if self.qualified_distinct_query_count is None:
            object.__setattr__(
                self, "qualified_distinct_query_count", self.distinct_query_count
            )
        if self.freshest_seed_evidence_at is None and self.freshest_evidence_at is not None:
            object.__setattr__(
                self, "freshest_seed_evidence_at", self.freshest_evidence_at
            )
        if self.is_search_candidate is None:
            object.__setattr__(
                self,
                "is_search_candidate",
                bool(SEARCH_DISCOVERY_CHANNELS.intersection(self.discovery_channels)),
            )
        if self.is_directory_candidate is None:
            object.__setattr__(
                self, "is_directory_candidate", "directory" in self.discovery_channels
            )


def selected_lane(candidate: PreliminarySourceCandidate) -> str:
    if candidate.is_linked_discussion:
        return "LINKED_DISCUSSION"
    if candidate.is_directory_candidate:
        return "DIRECTORY"
    if candidate.is_search_candidate:
        return "SEARCH"
    return "EXPLORATION"


def _freshness_key(value: datetime | None) -> float:
    return -_ensure_utc(value).timestamp() if value is not None else float("inf")


def preliminary_rank_key(candidate: PreliminarySourceCandidate) -> tuple:
    """Global buyer-first lexicographic order."""
    return (
        -candidate.strong_buyer_intent_count,
        -int(candidate.qualified_distinct_query_count or 0),
        -candidate.qualified_evidence_count,
        -candidate.potential_need_count,
        -int(candidate.is_linked_discussion),
        -int(bool(candidate.is_directory_candidate)),
        _freshness_key(candidate.freshest_seed_evidence_at),
        -int(candidate.raw_evidence_count or 0),
        candidate.telegram_id,
    )


def _lane_rank_key(candidate: PreliminarySourceCandidate, lane: str) -> tuple:
    common = (
        -candidate.strong_buyer_intent_count,
        -int(candidate.qualified_distinct_query_count or 0),
        -candidate.qualified_evidence_count,
        -candidate.potential_need_count,
    )
    if lane == "LINKED_DISCUSSION":
        return (*common, _freshness_key(candidate.freshest_seed_evidence_at), candidate.telegram_id)
    if lane == "DIRECTORY":
        return (
            *common,
            -int(candidate.directory_title_match),
            _freshness_key(candidate.freshest_seed_evidence_at),
            candidate.telegram_id,
        )
    if lane == "EXPLORATION":
        return (
            -candidate.strong_buyer_intent_count,
            -candidate.qualified_evidence_count,
            -candidate.potential_need_count,
            _freshness_key(candidate.freshest_seed_evidence_at),
            -int(candidate.raw_evidence_count or 0),
            candidate.telegram_id,
        )
    return preliminary_rank_key(candidate)


def select_preliminary_candidates(
    candidates: Sequence[PreliminarySourceCandidate],
    *,
    capacity: int = MAX_DEEP_VERIFICATION_SOURCES,
    diversity_reservations: Mapping[str, int] = DIVERSITY_RESERVATIONS,
) -> list[PreliminarySourceCandidate]:
    """Pure diversity admission followed by final global buyer-first ordering."""
    ids = [candidate.telegram_id for candidate in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError("preliminary_candidates_must_have_unique_telegram_ids")
    target = min(max(0, capacity), len(candidates))
    if target == 0:
        return []

    lanes = {candidate.telegram_id: selected_lane(candidate) for candidate in candidates}
    selected_phases: dict[int, str] = {}
    for lane in ("LINKED_DISCUSSION", "DIRECTORY", "EXPLORATION"):
        available = [
            candidate
            for candidate in candidates
            if lanes[candidate.telegram_id] == lane
            and candidate.telegram_id not in selected_phases
        ]
        ordered_lane = sorted(
            available, key=lambda item, _lane=lane: _lane_rank_key(item, _lane)
        )
        reserved_count = min(
            max(0, int(diversity_reservations.get(lane, 0))),
            target - len(selected_phases),
        )
        for candidate in ordered_lane[:reserved_count]:
            selected_phases[candidate.telegram_id] = "diversity_reserved"
        if len(selected_phases) == target:
            break

    remaining = [
        candidate for candidate in candidates if candidate.telegram_id not in selected_phases
    ]
    for candidate in sorted(remaining, key=preliminary_rank_key):
        if len(selected_phases) == target:
            break
        selected_phases[candidate.telegram_id] = "global_fill"

    selected = [candidate for candidate in candidates if candidate.telegram_id in selected_phases]
    ordered = sorted(selected, key=preliminary_rank_key)
    return [
        replace(
            candidate,
            selected_lane=lanes[candidate.telegram_id],
            selection_phase=selected_phases[candidate.telegram_id],
            selection_reason=(
                f"{selected_phases[candidate.telegram_id]}:{lanes[candidate.telegram_id]}"
            ),
            preliminary_position=position,
        )
        for position, candidate in enumerate(ordered, start=1)
    ]


def select_sources_for_deep_verification(
    candidates: Sequence[PreliminarySourceCandidate],
    *,
    limit: int = MAX_DEEP_VERIFICATION_SOURCES,
) -> list[PreliminarySourceCandidate]:
    """Compatibility alias for the Cycle-1 selector."""
    return select_preliminary_candidates(candidates, capacity=limit)


def build_preliminary_candidates(
    evidence: Sequence[EvidenceRecord],
    *,
    directory_sources: Sequence[SourceSnapshot] = (),
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
    snapshots = {snap.telegram_id: snap for snap in directory_sources}
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
    "preliminary_rank_key",
    "select_preliminary_candidates",
    "select_sources_for_deep_verification",
    "selected_lane",
]
