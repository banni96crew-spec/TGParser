from __future__ import annotations

# ruff: noqa: F403,F405,I001

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
    _restore_operator_seed_pool,
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
from telegram_lead_discovery.source_discovery.worker_parts.verification_pool import (
    _build_phase_candidates,
    _candidate_pool_item,
    _directory_ids_from_cursor,
    _refresh_phase_candidates,
    _select_phase_candidates,
    _should_rebuild_acquisition_pool,
)
from telegram_lead_discovery.source_discovery.worker_parts.verification_resume import (
    _resume_source_verification,
)


async def _phase_deep_verification(ctx: _WorkerContext) -> None:
    ctx.run.phase = "G"
    await ctx.session.flush()
    await _restore_directory_pool(ctx)
    await _restore_operator_seed_pool(ctx)
    run_cursor = _load_run_cursor(ctx)
    directory_candidate_ids = _directory_ids_from_cursor(run_cursor)
    evidence_rows = await _load_evidence_records(ctx)
    candidates = _build_phase_candidates(ctx, evidence_rows, directory_candidate_ids)
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
        selected = _select_phase_candidates(ctx, candidates, suppressed_ids)
        replacement_fetches = 0

        # SRC-040 / D-074: v8 must not run directory replacement.
        if (
            ctx.profile_version.version != 8
            and len(selected) < RUNTIME_CONFIG.MAX_DEEP_VERIFICATION_SOURCES
        ):
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
            candidates, selected = await _refresh_phase_candidates(
                ctx,
                run_cursor=_load_run_cursor(ctx),
                suppressed_ids=suppressed_ids,
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
