"""Pure diversity admission for deep source verification."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from telegram_lead_discovery.source_discovery.ranking_types import (
    DIVERSITY_RESERVATIONS,
    LANE_ADMISSION_ORDER,
    MAX_DEEP_VERIFICATION_SOURCES,
    PreliminarySourceCandidate,
    lane_rank_key,
    preliminary_rank_key,
    selected_lane,
)


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
    for lane in LANE_ADMISSION_ORDER:
        available = [
            candidate
            for candidate in candidates
            if lanes[candidate.telegram_id] == lane
            and candidate.telegram_id not in selected_phases
        ]
        ordered_lane = sorted(
            available, key=lambda item, _lane=lane: lane_rank_key(item, _lane)
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


__all__ = [
    "select_preliminary_candidates",
    "select_sources_for_deep_verification",
]
