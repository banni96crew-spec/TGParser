"""Acquisition-pool selection helpers for deep verification."""

from __future__ import annotations

from typing import Any

from telegram_lead_discovery.source_discovery.keyword_search import (
    build_preliminary_candidates,
    diversity_reservations_for_profile,
    select_preliminary_candidates,
)
from telegram_lead_discovery.source_discovery.worker_parts.core import _WorkerContext
from telegram_lead_discovery.source_discovery.worker_parts.dependencies import (
    RUNTIME_CONFIG,
)
from telegram_lead_discovery.source_discovery.worker_parts.repository import (
    _load_evidence_records,
)


def _candidate_pool_item(candidate: Any) -> dict[str, Any]:
    freshest = candidate.freshest_seed_evidence_at
    return {
        "telegram_id": candidate.telegram_id,
        "username": candidate.username,
        "title": candidate.title,
        "source_type": candidate.source_type,
        "public_url": f"https://t.me/{candidate.username}",
        "selection_phase": candidate.selection_phase,
        "selected_lane": candidate.selected_lane,
        "selection_reason": candidate.selection_reason,
        "preliminary_position": candidate.preliminary_position,
        "strong_buyer_intent_count": candidate.strong_buyer_intent_count,
        "qualified_evidence_count": candidate.qualified_evidence_count,
        "qualified_distinct_query_count": candidate.qualified_distinct_query_count,
        "potential_need_count": candidate.potential_need_count,
        "raw_evidence_count": candidate.raw_evidence_count,
        "hard_excluded_count": candidate.hard_excluded_count,
        "freshest_seed_evidence_at": freshest.isoformat() if freshest else None,
        "is_search_candidate": candidate.is_search_candidate,
        "is_directory_candidate": candidate.is_directory_candidate,
        "is_linked_discussion": candidate.is_linked_discussion,
        "linked_parent_telegram_id": candidate.linked_parent_telegram_id,
    }


def _should_rebuild_acquisition_pool(
    existing_pool: Any, *, verification_started: bool
) -> bool:
    return not (
        verification_started and isinstance(existing_pool, list) and bool(existing_pool)
    )


def _directory_ids_from_cursor(run_cursor: dict[str, Any]) -> set[int]:
    return {
        int(item["telegram_id"])
        for item in run_cursor.get("directory_pool") or []
        if isinstance(item, dict)
        and "telegram_id" in item
        and bool(item.get("is_directory_candidate", True))
    }


def _build_phase_candidates(
    ctx: _WorkerContext,
    evidence_rows: Any,
    directory_candidate_ids: set[int],
) -> list[Any]:
    return build_preliminary_candidates(
        evidence_rows,
        directory_sources=ctx.directory_sources,
        operator_seed_sources=ctx.operator_seed_sources,
        directory_query_texts=(
            *ctx.directory_queries,
            *ctx.replacement_directory_queries,
        ),
        directory_candidate_ids=directory_candidate_ids,
        linked_parent_ids=ctx.linked_parents,
        registry=ctx.registry,
        dismissed=ctx.dismissed,
        presented=ctx.presented,
    )


def _select_phase_candidates(
    ctx: _WorkerContext,
    candidates: list[Any],
    suppressed_ids: set[int],
) -> list[Any]:
    return select_preliminary_candidates(
        [item for item in candidates if item.telegram_id not in suppressed_ids],
        capacity=RUNTIME_CONFIG.MAX_DEEP_VERIFICATION_SOURCES,
        diversity_reservations=diversity_reservations_for_profile(
            directory_query_count=len(ctx.directory_queries),
            operator_seed_count=len(ctx.operator_seed_sources),
        ),
    )


async def _refresh_phase_candidates(
    ctx: _WorkerContext,
    *,
    run_cursor: dict[str, Any],
    suppressed_ids: set[int],
) -> tuple[list[Any], list[Any]]:
    directory_ids = _directory_ids_from_cursor(run_cursor)
    candidates = _build_phase_candidates(
        ctx, await _load_evidence_records(ctx), directory_ids
    )
    return candidates, _select_phase_candidates(ctx, candidates, suppressed_ids)
