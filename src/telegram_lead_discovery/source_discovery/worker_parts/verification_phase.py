from __future__ import annotations

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *

from telegram_lead_discovery.source_discovery.worker_parts.cap_finalize import (
    _finalize_unfinished_on_run_cap,
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


async def _phase_deep_verification(ctx: _WorkerContext) -> None:
    ctx.run.phase = "G"
    await ctx.session.flush()
    await _restore_directory_pool(ctx)
    evidence_rows = await _load_evidence_records(ctx)
    candidates = build_preliminary_candidates(
        evidence_rows,
        directory_sources=ctx.directory_sources,
        directory_query_texts=ctx.directory_queries,
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

    run_cursor = _load_run_cursor(ctx)
    existing_pool = run_cursor.get("acquisition_pool")
    if isinstance(existing_pool, list) and existing_pool:
        pool = [item for item in existing_pool if isinstance(item, dict)]
        cursor = int(run_cursor.get("acquisition_pool_cursor") or 0)
    else:
        ranked = sorted(candidates, key=preliminary_rank_key)
        pages = [
            tuple(c.telegram_id for c in ranked[:40]),
            tuple(c.telegram_id for c in ranked[40:80]),
            tuple(c.telegram_id for c in ranked[80:]),
        ]
        acquisition = acquire_with_replacement(
            [p for p in pages if p],
            is_suppressed=lambda tid, _s=suppressed_ids: tid in _s,
            target_quota=RUNTIME_CONFIG.MAX_DEEP_VERIFICATION_SOURCES,
        )
        replacement_fetches = acquisition.replacement_fetches_total
        pool_ids = [tid for tid in acquisition.qualified_candidate_ids if tid not in suppressed_ids]
        meta_by_id = {
            c.telegram_id: {
                "telegram_id": c.telegram_id,
                "username": c.username,
                "title": c.title,
                "source_type": c.source_type,
                "public_url": (f"https://t.me/{c.username}" if c.username else None),
            }
            for c in ranked
        }
        for snap in ctx.directory_sources:
            meta_by_id.setdefault(
                snap.telegram_id,
                {
                    "telegram_id": snap.telegram_id,
                    "username": snap.username,
                    "title": snap.title,
                    "source_type": snap.source_type,
                    "public_url": snap.public_url,
                },
            )

        # SRC-040 / D-069: after mass suppress, expand free directory queries
        # before declaring no_unseen_after_suppress.
        if len(pool_ids) < RUNTIME_CONFIG.MAX_DEEP_VERIFICATION_SOURCES:
            extra_fetches, expanded_ids = await _expand_directory_replacement(
                ctx,
                suppressed_ids=suppressed_ids,
                target_quota=RUNTIME_CONFIG.MAX_DEEP_VERIFICATION_SOURCES,
                already_qualified=len(pool_ids),
            )
            replacement_fetches += extra_fetches
            for tid in expanded_ids:
                if tid not in pool_ids and tid not in suppressed_ids:
                    pool_ids.append(tid)
                snap = next(
                    (s for s in ctx.directory_sources if s.telegram_id == tid),
                    None,
                )
                if snap is not None:
                    meta_by_id.setdefault(
                        tid,
                        {
                            "telegram_id": snap.telegram_id,
                            "username": snap.username,
                            "title": snap.title,
                            "source_type": snap.source_type,
                            "public_url": snap.public_url,
                        },
                    )
            # Refresh suppress sets after expansion may have noted more.
            suppressed_ids = (
                set(ctx.registry_suppressed_ids)
                | set(ctx.dismissed_suppressed_ids)
                | set(ctx.presented_suppressed_ids)
            )
            pool_ids = [tid for tid in pool_ids if tid not in suppressed_ids]

        if replacement_fetches:
            await _bump_counter(ctx, "replacement_fetches_total", replacement_fetches)

        pool = [meta_by_id[tid] for tid in pool_ids if tid in meta_by_id]
        cursor = 0
        await _persist_acquisition_pool(ctx, pool=pool, pool_cursor=cursor)
        pool_exhausted = len(pool) < RUNTIME_CONFIG.MAX_DEEP_VERIFICATION_SOURCES
        if pool_exhausted:
            reason = (
                "provider_empty"
                if acquisition.acquired_total == 0 and replacement_fetches == 0
                else "no_unseen_after_suppress"
            )
            counters = _loads_counters(ctx.run.counters_json)
            merged = merge_funnel_counters(
                counters,
                pool_exhausted=True,
                pool_exhausted_reason=reason,
                acquired_total=max(acquisition.acquired_total, len(meta_by_id), len(pool)),
                suppressed_total=len(suppressed_ids),
                replacement_fetches_total=replacement_fetches,
            )
            ctx.run.counters_json = _dumps_counters(merged)

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
            await _finalize_unfinished_on_run_cap(
                ctx, pool=pool, done_sources=done_sources, suppressed_ids=suppressed_ids
            )
            break
        if await _gate_satisfied_from_persisted(ctx):
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
            counters = _loads_counters(ctx.run.counters_json)
            if len(pool) > 0 and not counters.get("pool_exhausted"):
                merged = merge_funnel_counters(
                    counters,
                    pool_exhausted=True,
                    pool_exhausted_reason="verification_pool_exhausted",
                    acquired_total=len(pool),
                    suppressed_total=len(suppressed_ids),
                    replacement_fetches_total=int(counters.get("replacement_fetches_total", 0)),
                )
                ctx.run.counters_json = _dumps_counters(merged)
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
