"""Types and lane keys for preliminary deep-verification admission."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from telegram_lead_discovery.source_discovery.evidence import DiscoveryChannel
from telegram_lead_discovery.source_discovery.identity import _ensure_utc

MAX_DEEP_VERIFICATION_SOURCES = 25
STRONG_BUYER_CATEGORIES = frozenset(
    {"direct_order", "contractor_search", "recommendation_request"}
)
SEARCH_DISCOVERY_CHANNELS = frozenset({"global_message", "public_posts"})
LANE_ADMISSION_ORDER = (
    "OPERATOR_SEED",
    "LINKED_DISCUSSION",
    "DIRECTORY",
    "EXPLORATION",
)
DIVERSITY_RESERVATIONS: Mapping[str, int] = {
    "LINKED_DISCUSSION": 3,
    "DIRECTORY": 0,
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
    is_operator_seed_candidate: bool | None = None
    is_linked_discussion: bool = False
    linked_parent_telegram_id: int | None = None
    discovery_channels: tuple[DiscoveryChannel, ...] = ()
    selection_phase: str | None = None
    selected_lane: str | None = None
    selection_reason: str | None = None
    preliminary_position: int | None = None
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
        if self.is_operator_seed_candidate is None:
            object.__setattr__(
                self,
                "is_operator_seed_candidate",
                "operator_seed" in self.discovery_channels,
            )


def selected_lane(candidate: PreliminarySourceCandidate) -> str:
    if candidate.is_operator_seed_candidate:
        return "OPERATOR_SEED"
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
    """Global buyer-first lexicographic order (no directory bit)."""
    return (
        -candidate.strong_buyer_intent_count,
        -int(candidate.qualified_distinct_query_count or 0),
        -candidate.qualified_evidence_count,
        -candidate.potential_need_count,
        -int(candidate.is_linked_discussion),
        _freshness_key(candidate.freshest_seed_evidence_at),
        -int(candidate.raw_evidence_count or 0),
        candidate.telegram_id,
    )


def lane_rank_key(candidate: PreliminarySourceCandidate, lane: str) -> tuple:
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


def diversity_reservations_for_profile(
    *,
    directory_query_count: int = 0,
    operator_seed_count: int = 0,
) -> dict[str, int]:
    directory = 3 if int(directory_query_count) > 0 else 0
    return {
        "OPERATOR_SEED": min(
            MAX_DEEP_VERIFICATION_SOURCES, max(0, int(operator_seed_count))
        ),
        "LINKED_DISCUSSION": 3,
        "DIRECTORY": directory,
        "EXPLORATION": 1,
    }
