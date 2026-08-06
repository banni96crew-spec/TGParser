from __future__ import annotations

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *

from telegram_lead_discovery.source_discovery.worker_parts.core import (
    _CancelRequested,
    _WorkerContext,
    _dumps_counters,
    _loads_counters,
    _utcnow,
)


async def _check_cancel(ctx: _WorkerContext) -> None:
    await ctx.session.refresh(ctx.job)
    if ctx.job.cancel_requested_at is not None:
        ctx.run.state = "cancelling"
        await ctx.session.flush()
        raise _CancelRequested()
    await ctx.session.refresh(ctx.run)
    if ctx.run.state == "cancelling":
        raise _CancelRequested()


async def _commit_before_network(ctx: _WorkerContext) -> None:
    """End the current SQLite transaction before Telegram I/O (plan §7)."""
    await ctx.session.commit()


async def _maybe_heartbeat(ctx: _WorkerContext) -> None:
    now = _utcnow()
    if (now - ctx.last_heartbeat_at).total_seconds() >= RUNTIME_CONFIG.HEARTBEAT_SECONDS:
        await heartbeat_job(ctx.session, ctx.job)
        ctx.last_heartbeat_at = now


async def _bump_counter(ctx: _WorkerContext, key: str, delta: int) -> None:
    counters = _loads_counters(ctx.run.counters_json)
    counters[key] = int(counters.get(key, 0)) + delta
    ctx.run.counters_json = _dumps_counters(counters)
