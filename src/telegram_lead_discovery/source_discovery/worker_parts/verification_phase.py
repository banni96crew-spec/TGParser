from __future__ import annotations

# ruff: noqa: F403,F405,I001

from typing import Any

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *

from telegram_lead_discovery.source_discovery.worker_parts.cap_finalize import (
    _finalize_unfinished_on_run_cap,
)
from telegram_lead_discovery.source_discovery.worker_parts.acquisition_state import (
    _classify_acquisition_stop,
)
from telegram_lead_discovery.source_discovery.worker_parts.control import (
    _bump_counter,
    _check_cancel,
    _maybe_heartbeat,
)
from telegram_lead_discovery.source_discovery.worker_parts.core import (
    _WorkerContext,
    _dumps_counters,
    _loads_counters,
)
from telegram_lead_discovery.source_discovery.worker_parts.history_state import (
    _get_or_create_verification_query,
    _load_run_cursor,
    _restore_directory_pool,
    _run_history_scanned,
    _verification_started,
    _verification_scanned_by_source,
)
from telegram_lead_discovery.source_discovery.worker_parts.persistence import (
    _note_dismissed_suppressed,
    _note_presented_suppressed,
    _note_registry_suppressed,
)
from telegram_lead_discovery.source_discovery.worker_parts.query_state import (
    _finished_verification_sources,
    _resumable_verification_queries,
)
from telegram_lead_discovery.source_discovery.worker_parts.registry import (
    _dismissed_canonical_id,
    _presented_canonical_id,
)
from telegram_lead_discovery.source_discovery.worker_parts.replacement import (
    _expand_directory_replacement,
)
from telegram_lead_discovery.source_discovery.worker_parts.repository import (
    _load_evidence_records,
    _next_ordinal,
)
from telegram_lead_discovery.source_discovery.worker_parts.truth_state import (
    _gate_satisfied_from_persisted,
    _persist_acquisition_pool,
)
from telegram_lead_discovery.source_discovery.worker_parts.verification_resume import (
    _resume_source_verification,
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


async def _phase_deep_verification(ctx: _WorkerContext) -> None:
    ctx.run.phase = "G"
    await ctx.session.flush()
    await _restore_directory_pool(ctx)
    run_cursor = _load_run_cursor(ctx)
    directory_candidate_ids = {
        int(item["telegram_id"])
        for item in run_cursor.get("directory_pool") or []
        if isinstance(item, dict)
        and "telegram_id" in item
        and bool(item.get("is_directory_candidate", True))
    }
    evidence_rows = await _load_evidence_records(ctx)
    candidates = build_preliminary_candidates(
        evidence_rows,
        directory_sources=ctx.directory_sources,
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
    known = registry_telegram_ids(ctx.registry)
    dir_suppressed = {s.telegram_id for s in ctx.directory_sources if s.telegram_id in known}
    await _note_registry_suppressed(ctx, dir_suppressed)
    dir_dismissed = {
        matched_id
        for s in ctx.directory_sources
        if (
            matched_id := _dismissed_canonical_id(
                ctx,
                telegram_id=s.telegram_id,
                username=s.username,
            )
        )
        is not None
    }
    await _note_dismissed_suppressed(ctx, dir_dismissed)
    dir_presented = {
        matched_id
        for s in ctx.directory_sources
        if (
            matched_id := _presented_canonical_id(
                ctx,
                telegram_id=s.telegram_id,
                username=s.username,
            )
        )
        is not None
    }
    await _note_presented_suppressed(ctx, dir_presented)
    suppressed_ids = (
        set(ctx.registry_suppressed_ids)
        | set(ctx.dismissed_suppressed_ids)
        | set(ctx.presented_suppressed_ids)
    )

    existing_pool = run_cursor.get("acquisition_pool")
    verification_started = await _verification_started(ctx)
    if not _should_rebuild_acquisition_pool(
        existing_pool, verification_started=verification_started
    ):
        # Once any source_verification query exists, persisted membership, order,
        # and diagnostics are immutable for this run.
        pool = [item for item in existing_pool if isinstance(item, dict)]
        suppressed_ids.difference_update(
            int(item["telegram_id"]) for item in pool if "telegram_id" in item
        )
        cursor = int(run_cursor.get("acquisition_pool_cursor") or 0)
    else:
        eligible_candidates = [
            candidate for candidate in candidates if candidate.telegram_id not in suppressed_ids
        ]
        selected = select_preliminary_candidates(
            eligible_candidates,
            capacity=RUNTIME_CONFIG.MAX_DEEP_VERIFICATION_SOURCES,
        )
        replacement_fetches = 0

        # SRC-040 / D-069: after mass suppress, expand free directory queries
        # before declaring no_unseen_after_suppress.
        if len(selected) < RUNTIME_CONFIG.MAX_DEEP_VERIFICATION_SOURCES:
            extra_fetches, _expanded_ids = await _expand_directory_replacement(
                ctx,
                suppressed_ids=suppressed_ids,
                target_quota=RUNTIME_CONFIG.MAX_DEEP_VERIFICATION_SOURCES,
                already_qualified=len(selected),
            )
            replacement_fetches += extra_fetches
            # Replacement rejoins the full builder -> selector path; no direct
            # pool append and no synthetic buyer metrics.
            suppressed_ids = (
                set(ctx.registry_suppressed_ids)
                | set(ctx.dismissed_suppressed_ids)
                | set(ctx.presented_suppressed_ids)
            )
            refreshed_cursor = _load_run_cursor(ctx)
            directory_candidate_ids = {
                int(item["telegram_id"])
                for item in refreshed_cursor.get("directory_pool") or []
                if isinstance(item, dict)
                and "telegram_id" in item
                and bool(item.get("is_directory_candidate", True))
            }
            candidates = build_preliminary_candidates(
                await _load_evidence_records(ctx),
                directory_sources=ctx.directory_sources,
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
            selected = select_preliminary_candidates(
                [
                    candidate
                    for candidate in candidates
                    if candidate.telegram_id not in suppressed_ids
                ],
                capacity=RUNTIME_CONFIG.MAX_DEEP_VERIFICATION_SOURCES,
            )

        if replacement_fetches:
            await _bump_counter(ctx, "replacement_fetches_total", replacement_fetches)

        pool = [_candidate_pool_item(candidate) for candidate in selected]
        cursor = 0
        await _persist_acquisition_pool(ctx, pool=pool, pool_cursor=cursor)
        pool_exhausted, reason, termination_reason = await _classify_acquisition_stop(
            ctx,
            pool_size=len(pool),
            acquired_total=len(candidates),
        )
        if pool_exhausted:
            if reason is None:
                raise RuntimeError("pool_exhausted_reason_missing")
            counters = _loads_counters(ctx.run.counters_json)
            merged = merge_funnel_counters(
                counters,
                pool_exhausted=True,
                pool_exhausted_reason=reason,
                acquired_total=max(len(candidates), len(pool)),
                suppressed_total=len(suppressed_ids),
                replacement_fetches_total=replacement_fetches,
            )
            ctx.run.counters_json = _dumps_counters(merged)
            ctx.run.pool_exhausted = True
            ctx.run.pool_exhausted_reason = reason
            ctx.run.run_termination_reason = reason
        else:
            ctx.run.pool_exhausted = False
            ctx.run.pool_exhausted_reason = None
            ctx.run.run_termination_reason = termination_reason

    if ctx.presented_suppressed_ids:
        counters = _loads_counters(ctx.run.counters_json)
        unique = len(ctx.presented_suppressed_ids)
        counters["presented_suppressed"] = unique
        counters["cooldown_suppressed"] = unique
        ctx.run.counters_json = _dumps_counters(counters)
    record_verified_sources(len(pool))
    ctx.run.phase = "H"
    await ctx.session.flush()

    done_sources = await _finished_verification_sources(ctx)
    next_ordinal = await _next_ordinal(ctx)
    finished_or_suppressed = set(done_sources) | set(suppressed_ids)

    # Crash / FloodWait resume: continue the same source (SRC-048), one page, then fair loop.
    for query in await _resumable_verification_queries(ctx):
        await _resume_source_verification(ctx, query, max_pages=1)
        if query.source_telegram_id is not None and query.state == "succeeded":
            done_sources.add(query.source_telegram_id)
            finished_or_suppressed.add(query.source_telegram_id)
        elif query.state == "retry_wait":
            return

    # Fair page waterfill: probe later candidates before early weak sources hit 1500.
    while True:
        await _check_cancel(ctx)
        await _maybe_heartbeat(ctx)
        if await _run_history_scanned(ctx) >= RUNTIME_CONFIG.HISTORY_SCAN_CAP_PER_RUN:
            ctx.run.pool_exhausted = False
            ctx.run.pool_exhausted_reason = None
            ctx.run.run_termination_reason = "history_run_cap"
            await _finalize_unfinished_on_run_cap(
                ctx, pool=pool, done_sources=done_sources, suppressed_ids=suppressed_ids
            )
            break
        if await _gate_satisfied_from_persisted(ctx):
            ctx.run.run_termination_reason = "quality_reached"
            break

        scanned_by = await _verification_scanned_by_source(ctx)
        pool_ids = [int(item["telegram_id"]) for item in pool]
        tid = pick_next_fair_source(
            pool_telegram_ids=pool_ids,
            scanned_by_source=scanned_by,
            finished_sources=finished_or_suppressed,
            source_cap=RUNTIME_CONFIG.HISTORY_SCAN_CAP_PER_SOURCE,
        )
        if tid is None:
            if not ctx.run.pool_exhausted and ctx.run.run_termination_reason is None:
                ctx.run.run_termination_reason = "deep_candidate_cap"
            break

        # Observability cursor: furthest pool index touched (not sequential monopoly).
        try:
            touched_idx = pool_ids.index(tid)
        except ValueError:
            touched_idx = cursor
        cursor = max(cursor, touched_idx + 1)
        await _persist_acquisition_pool(ctx, pool=pool, pool_cursor=cursor)

        query = await _get_or_create_verification_query(
            ctx, telegram_id=tid, next_ordinal=next_ordinal
        )
        if query.ordinal >= next_ordinal:
            next_ordinal = query.ordinal + 1
        await _resume_source_verification(ctx, query, max_pages=1)
        if query.state == "succeeded":
            done_sources.add(tid)
            finished_or_suppressed.add(tid)
        elif query.state == "retry_wait":
            return
