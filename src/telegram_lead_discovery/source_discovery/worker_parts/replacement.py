from __future__ import annotations

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *

from telegram_lead_discovery.source_discovery.worker_parts.core import _WorkerContext
from telegram_lead_discovery.source_discovery.worker_parts.control import (
    _check_cancel,
    _maybe_heartbeat,
)
from telegram_lead_discovery.source_discovery.worker_parts.persistence import (
    _note_dismissed_suppressed,
    _note_presented_suppressed,
    _note_registry_suppressed,
)
from telegram_lead_discovery.source_discovery.worker_parts.registry import (
    _dismissed_canonical_id,
    _presented_canonical_id,
)
from telegram_lead_discovery.source_discovery.worker_parts.repository import _next_ordinal
from telegram_lead_discovery.source_discovery.worker_parts.seed_queries import (
    _execute_directory_query,
)


async def _expand_directory_replacement(
    ctx: _WorkerContext,
    *,
    suppressed_ids: set[int],
    target_quota: int,
    already_qualified: int,
) -> tuple[int, list[int]]:
    """Free directory expansion after mass suppress (SRC-040 / D-069).

    Uses only replacement queries frozen in the run's immutable profile version,
    plus profile directory texts not yet executed. Stars/paid paths are never used.
    """
    if already_qualified >= target_quota:
        return 0, []

    existing = list(
        (
            await ctx.session.execute(
                select(DiscoveryRunQuery).where(
                    DiscoveryRunQuery.run_id == ctx.run.id,
                    DiscoveryRunQuery.query_kind == "directory",
                )
            )
        )
        .scalars()
        .all()
    )
    already_texts = {normalize_query(q.query_text) for q in existing if q.query_text}
    candidates: list[str] = []
    for raw in (*ctx.directory_queries, *ctx.replacement_directory_queries):
        try:
            normalized = normalize_query(raw)
        except Exception:
            continue
        if len(normalized) < 3:
            continue
        if normalized in already_texts:
            continue
        if normalized in candidates:
            continue
        candidates.append(normalized)

    fetches = 0
    new_ids: list[int] = []
    need = target_quota - already_qualified
    next_ordinal = await _next_ordinal(ctx)

    for query_text in candidates:
        if len(new_ids) >= need:
            break
        await _check_cancel(ctx)
        await _maybe_heartbeat(ctx)
        query = DiscoveryRunQuery(
            run_id=ctx.run.id,
            ordinal=next_ordinal,
            query_kind="directory",
            query_text=query_text,
            scope=None,
            state="queued",
        )
        next_ordinal += 1
        ctx.session.add(query)
        await ctx.session.flush()
        before_ids = {s.telegram_id for s in ctx.directory_sources}
        await _execute_directory_query(ctx, query)
        fetches += 1
        # Note suppress on newly acquired peers.
        for snap in ctx.directory_sources:
            if snap.telegram_id in before_ids:
                continue
            if snap.telegram_id in registry_telegram_ids(ctx.registry):
                await _note_registry_suppressed(ctx, {snap.telegram_id})
                continue
            dismissed_id = _dismissed_canonical_id(
                ctx, telegram_id=snap.telegram_id, username=snap.username
            )
            if dismissed_id is not None:
                await _note_dismissed_suppressed(ctx, {dismissed_id})
                continue
            presented_id = _presented_canonical_id(
                ctx, telegram_id=snap.telegram_id, username=snap.username
            )
            if presented_id is not None:
                await _note_presented_suppressed(ctx, {presented_id})
                continue
            if snap.telegram_id not in suppressed_ids and snap.telegram_id not in new_ids:
                new_ids.append(snap.telegram_id)

    return fetches, new_ids
