from __future__ import annotations

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *

from telegram_lead_discovery.source_discovery.worker_parts.core import (
    _FloodWaitControl,
    _WorkerContext,
    _dumps_counters,
    _ensure_utc,
    _loads_counters,
    _utcnow,
)
from telegram_lead_discovery.source_discovery.worker_parts.repository import (
    _evidence_count,
    _opportunity_count,
)


async def _park_flood_wait(ctx: _WorkerContext, exc: _FloodWaitControl) -> dict[str, Any]:
    until = _ensure_utc(exc.until)
    query = exc.query
    query.state = "retry_wait"
    query.available_at = until
    is_flood = query.error_code in (None, "flood_wait") or "flood" in (query.error_code or "")
    if is_flood and query.error_code != "transient_error":
        query.error_code = "flood_wait"
        ctx.run.state = "retry_wait_flood"
        ctx.run.last_error_code = "flood_wait"
        note_flood_wait(until=until)
    else:
        # Transient retry: keep run running (no long sleep).
        ctx.run.state = "running"
        ctx.run.last_error_code = query.error_code
    ctx.job.state = "retry_wait"
    ctx.job.available_at = until
    ctx.job.last_error_code = query.error_code
    ctx.job.lease_until = None
    ctx.job.updated_at = _utcnow()
    await ctx.session.flush()
    log_query_progress(
        run_id=ctx.run.id,
        query_ordinal=query.ordinal,
        method=query.query_kind or "unknown",
        result_count=int(query.result_count or 0),
        error_code=query.error_code,
        duration_ms=None,
        outcome="retry_wait",
    )
    return {
        "outcome": "retry_wait",
        "until": until.isoformat(),
        "query_id": query.id,
        "error_code": query.error_code,
    }


async def _mark_cancelled(ctx: _WorkerContext) -> dict[str, Any]:
    now = _utcnow()
    ctx.run.state = "cancelled"
    ctx.run.finished_at = now
    ctx.run.phase = ctx.run.phase or "cancelled"
    ctx.job.state = "cancelled"
    ctx.job.lease_until = None
    ctx.job.updated_at = now
    # Cancel remaining queued queries.
    result = await ctx.session.execute(
        select(DiscoveryRunQuery).where(
            DiscoveryRunQuery.run_id == ctx.run.id,
            DiscoveryRunQuery.state.in_(("queued", "running", "retry_wait")),
        )
    )
    for query in result.scalars():
        query.state = "cancelled"
        query.finished_at = now
    await ctx.session.flush()
    _emit_run_observability(
        ctx.run,
        state="cancelled",
        evidence_count=None,
        unique_sources=None,
    )
    note_run_recovered()
    return {"outcome": "cancelled", "run_id": ctx.run.id}


async def _finish_run(ctx: _WorkerContext) -> dict[str, Any]:
    result = await ctx.session.execute(
        select(DiscoveryRunQuery).where(DiscoveryRunQuery.run_id == ctx.run.id)
    )
    queries = list(result.scalars().all())
    has_partial = any(q.state in ("quota_skipped", "budget_skipped", "failed") for q in queries)
    now = _utcnow()
    ctx.run.state = "partial" if has_partial else "succeeded"
    ctx.run.finished_at = now
    ctx.run.phase = "I"
    ctx.run.last_error_code = None
    ctx.job.state = "succeeded"
    ctx.job.lease_until = None
    ctx.job.last_error_code = None
    ctx.job.updated_at = now
    counters = _loads_counters(ctx.run.counters_json)
    counters["evidence_count"] = await _evidence_count(ctx)
    counters["unique_sources"] = await _opportunity_count(ctx)
    ctx.run.counters_json = _dumps_counters(counters)
    await ctx.session.flush()
    _emit_run_observability(
        ctx.run,
        state=ctx.run.state,
        evidence_count=counters["evidence_count"],
        unique_sources=counters["unique_sources"],
    )
    note_run_recovered()
    return {
        "outcome": ctx.run.state,
        "run_id": ctx.run.id,
        "evidence_count": counters["evidence_count"],
        "unique_sources": counters["unique_sources"],
    }


async def _fail_run(
    session: AsyncSession,
    job: Job,
    run: DiscoveryRun,
    code: str,
) -> dict[str, Any]:
    now = _utcnow()
    run.state = "failed"
    run.finished_at = now
    run.last_error_code = code
    job.state = "failed"
    job.last_error_code = code
    job.lease_until = None
    job.updated_at = now
    await session.flush()
    _emit_run_observability(
        run,
        state="failed",
        evidence_count=None,
        unique_sources=None,
        error_code=code,
    )
    return {"outcome": "failed", "error": code, "run_id": run.id}


def _emit_run_observability(
    run: DiscoveryRun,
    *,
    state: str,
    evidence_count: int | None,
    unique_sources: int | None,
    error_code: str | None = None,
) -> None:
    record_run_total(state)
    duration_ms: int | None = None
    if run.started_at is not None and run.finished_at is not None:
        started = _ensure_utc(run.started_at)
        finished = _ensure_utc(run.finished_at)
        seconds = max(0.0, (finished - started).total_seconds())
        record_run_duration_seconds(seconds)
        duration_ms = int(seconds * 1000)
    if unique_sources is not None:
        record_unique_sources(unique_sources)
    if evidence_count is not None:
        # Qualified count is emitted during finalize; keep total evidence in logs only.
        pass
    counters = _loads_counters(run.counters_json)
    record_funnel_observability(counters)
    log_run_finished(
        run_id=run.id,
        state=state,
        duration_ms=duration_ms,
        error_code=error_code or run.last_error_code,
        evidence_count=evidence_count,
        unique_sources=unique_sources,
    )


__all__ = [
    "CLAIM_LOOP_IDLE_SECONDS",
    "CLAIM_LOOP_SHUTDOWN_TIMEOUT_SECONDS",
    "DEEP_QUERIES_PER_SOURCE",
    "DIRECTORY_PEER_LIMIT",
    "GLOBAL_MAX_PAGES",
    "GLOBAL_PAGE_SIZE",
    "HEARTBEAT_SECONDS",
    "LEASE_SECONDS",
    "MAX_TRANSIENT_ATTEMPTS",
    "TRANSIENT_RETRY_DELAYS_S",
    "GraphDiscoveryClaimLoop",
    "KeywordDiscoveryClaimLoop",
    "claim_and_process_graph_job",
    "claim_and_process_keyword_job",
    "process_graph_discovery_job",
    "process_keyword_discovery_job",
]
