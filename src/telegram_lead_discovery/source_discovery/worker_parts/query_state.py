from __future__ import annotations

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *

from telegram_lead_discovery.source_discovery.worker_parts.core import (
    _WorkerContext,
    _cursor_payload,
    _ensure_utc,
    _save_cursor,
    _transient_delay_seconds,
    _utcnow,
)
from telegram_lead_discovery.source_discovery.worker_parts.control import _bump_counter


async def _mark_query_terminal(
    query: DiscoveryRunQuery,
    state: str,
    *,
    error_code: str | None = None,
) -> None:
    query.state = state
    if error_code is not None:
        query.error_code = error_code
    query.finished_at = _utcnow()
    if state != "retry_wait":
        query.available_at = None
    _emit_query_observability(query, state=state, error_code=query.error_code)


def _emit_query_observability(
    query: DiscoveryRunQuery,
    *,
    state: str,
    error_code: str | None,
) -> None:
    kind = query.query_kind or "unknown"
    record_query_total(kind=kind, outcome=state)
    if state == "quota_skipped":
        # OBS-018: quota exhaustion alone must not mark discovery unhealthy.
        note_quota_skipped()
    duration_ms: int | None = None
    if query.started_at is not None and query.finished_at is not None:
        started = _ensure_utc(query.started_at)
        finished = _ensure_utc(query.finished_at)
        duration_ms = max(0, int((finished - started).total_seconds() * 1000))
    quota_outcome = None
    if state == "quota_skipped":
        quota_outcome = error_code or "quota_exhausted"
    log_query_progress(
        run_id=query.run_id,
        query_ordinal=query.ordinal,
        method=kind,
        result_count=int(query.result_count or 0),
        error_code=error_code,
        duration_ms=duration_ms,
        quota_outcome=quota_outcome,
        outcome=state,
    )


async def _handle_transient(
    ctx: _WorkerContext,
    query: DiscoveryRunQuery,
    error_code: str,
) -> bool:
    """Return True when the job should park in retry_wait; False if query failed."""
    payload = _cursor_payload(query.cursor_json)
    attempts = int(payload.get("transient_attempts", 0)) + 1
    payload["transient_attempts"] = attempts
    _save_cursor(query, payload)
    query.error_code = error_code
    if attempts >= RUNTIME_CONFIG.MAX_TRANSIENT_ATTEMPTS:
        await _mark_query_terminal(query, "failed", error_code=error_code)
        await _bump_counter(ctx, "failed_queries", 1)
        return False
    note_transient_error()
    delay = _transient_delay_seconds(attempts)
    until = _utcnow() + timedelta(seconds=delay)
    query.state = "retry_wait"
    query.available_at = until
    return True


async def _restore_linked_parents(ctx: _WorkerContext) -> None:
    snaps = (
        await ctx.session.execute(
            select(SourceOpportunitySnapshot).where(
                SourceOpportunitySnapshot.run_id == ctx.run.id,
                SourceOpportunitySnapshot.linked_parent_telegram_id.is_not(None),
            )
        )
    ).scalars()
    for snap in snaps:
        parent = snap.linked_parent_telegram_id
        if parent is not None:
            ctx.linked_parents[snap.source_telegram_id] = parent


async def _source_ids_with_query_kind(ctx: _WorkerContext, query_kind: str) -> set[int]:
    result = await ctx.session.execute(
        select(DiscoveryRunQuery).where(
            DiscoveryRunQuery.run_id == ctx.run.id,
            DiscoveryRunQuery.query_kind == query_kind,
        )
    )
    out: set[int] = set()
    for row in result.scalars():
        if row.source_telegram_id is not None:
            out.add(row.source_telegram_id)
    return out


async def _parked_queries(
    ctx: _WorkerContext,
    query_kind: str,
) -> list[DiscoveryRunQuery]:
    result = await ctx.session.execute(
        select(DiscoveryRunQuery)
        .where(
            DiscoveryRunQuery.run_id == ctx.run.id,
            DiscoveryRunQuery.query_kind == query_kind,
            DiscoveryRunQuery.state == "retry_wait",
        )
        .order_by(DiscoveryRunQuery.ordinal.asc())
    )
    return list(result.scalars().all())


_TERMINAL_VERIFICATION_STATES = frozenset(
    {
        "succeeded",
        "failed",
        "cancelled",
        "quota_skipped",
        "budget_skipped",
    }
)


async def _resumable_verification_queries(ctx: _WorkerContext) -> list[DiscoveryRunQuery]:
    """Return crash ``running`` and ``retry_wait`` source_verification queries.

    Future ``retry_wait`` (available_at > now) is still returned; resume raises
    FloodWaitControl to park until exact ``until``.
    """
    result = await ctx.session.execute(
        select(DiscoveryRunQuery)
        .where(
            DiscoveryRunQuery.run_id == ctx.run.id,
            DiscoveryRunQuery.query_kind == "source_verification",
            DiscoveryRunQuery.state.in_(("running", "retry_wait")),
        )
        .order_by(DiscoveryRunQuery.ordinal.asc())
    )
    return list(result.scalars().all())


async def _finished_verification_sources(ctx: _WorkerContext) -> set[int]:
    """Sources whose verification query reached a true terminal state only."""
    result = await ctx.session.execute(
        select(DiscoveryRunQuery).where(
            DiscoveryRunQuery.run_id == ctx.run.id,
            DiscoveryRunQuery.query_kind == "source_verification",
            DiscoveryRunQuery.state.in_(tuple(_TERMINAL_VERIFICATION_STATES)),
        )
    )
    keys: set[int] = set()
    for row in result.scalars():
        if row.source_telegram_id is None:
            continue
        keys.add(row.source_telegram_id)
    return keys
