from __future__ import annotations

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *
from telegram_lead_discovery.source_discovery.worker_parts.core import _dumps_counters, _utcnow


TERMINAL_GRAPH_LIKE = frozenset({"succeeded", "failed", "cancelled"})


@dataclass
class _GraphWorkerContext:
    session: AsyncSession
    gateway: TelegramGateway
    job: Job
    run: DiscoveryRun
    budget: Any  # GraphBudget — imported lazily below
    registry: SourceRegistryIndex
    dismissed: DismissedKeywordSourceIndex
    cancel_requested: bool = False
    last_heartbeat_at: datetime = field(default_factory=_utcnow)
    queue: list[Any] = field(default_factory=list)
    parent_by_telegram_id: dict[int, int] = field(default_factory=dict)


def _save_graph_cursor(ctx: _GraphWorkerContext) -> None:
    payload = {
        "resolved_canonical_keys": sorted(ctx.budget.resolved_canonical_keys),
        "queue": [
            {
                "seed_telegram_id": q.seed_telegram_id,
                "seed_source_id": q.seed_source_id,
                "depth": q.depth,
                "username": q.username,
            }
            for q in ctx.queue
        ],
    }
    ctx.run.cursor_json = json.dumps(payload, ensure_ascii=False)
    ctx.run.counters_json = _dumps_counters(ctx.budget.to_counters())


async def _graph_maybe_heartbeat(ctx: _GraphWorkerContext) -> None:
    now = _utcnow()
    if (now - ctx.last_heartbeat_at).total_seconds() >= RUNTIME_CONFIG.HEARTBEAT_SECONDS:
        await heartbeat_job(ctx.session, ctx.job)
        ctx.last_heartbeat_at = now


async def _park_graph_flood(ctx: _GraphWorkerContext, until: datetime) -> dict[str, Any]:
    note_flood_wait(until=until)
    ctx.job.state = "retry_wait"
    ctx.job.available_at = until
    ctx.job.last_error_code = "flood_wait"
    ctx.job.updated_at = _utcnow()
    # Run stays running (degraded) with cursor preserved (SRC-042).
    ctx.run.state = "running"
    ctx.run.phase = "retry_wait"
    ctx.run.last_error_code = "flood_wait"
    await ctx.session.flush()
    return {"outcome": "retry_wait", "until": until.isoformat(), "run_id": ctx.run.id}


async def _finish_graph_success(ctx: _GraphWorkerContext) -> dict[str, Any]:
    now = _utcnow()
    ctx.run.state = "succeeded"
    ctx.run.finished_at = now
    ctx.run.phase = "done"
    ctx.run.counters_json = _dumps_counters(ctx.budget.to_counters())
    ctx.run.cursor_json = json.dumps(
        {"resolved_canonical_keys": sorted(ctx.budget.resolved_canonical_keys)},
        ensure_ascii=False,
    )
    ctx.job.state = "succeeded"
    ctx.job.lease_until = None
    ctx.job.updated_at = now
    await ctx.session.flush()
    return {
        "outcome": "succeeded",
        "run_id": ctx.run.id,
        "counters": ctx.budget.to_counters(),
    }


async def _finish_graph_cancelled(ctx: _GraphWorkerContext) -> dict[str, Any]:
    now = _utcnow()
    _save_graph_cursor(ctx)
    ctx.run.state = "cancelled"
    ctx.run.finished_at = now
    ctx.run.last_error_code = "cancel_requested"
    ctx.job.state = "cancelled"
    ctx.job.lease_until = None
    ctx.job.updated_at = now
    await ctx.session.flush()
    return {"outcome": "cancelled", "run_id": ctx.run.id}
