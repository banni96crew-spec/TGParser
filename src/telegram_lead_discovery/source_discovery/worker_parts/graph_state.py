from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.collector.ports import TelegramGateway
from telegram_lead_discovery.observability.discovery import (
    note_flood_wait,
)
from telegram_lead_discovery.source_discovery.identity import (
    DismissedKeywordSourceIndex,
    SourceRegistryIndex,
)
from telegram_lead_discovery.source_discovery.worker_parts.core import _dumps_counters, _utcnow
from telegram_lead_discovery.source_discovery.worker_parts.dependencies import (
    RUNTIME_CONFIG,
)
from telegram_lead_discovery.storage.jobs import heartbeat_job
from telegram_lead_discovery.storage.models import DiscoveryRun, Job

TERMINAL_GRAPH_LIKE = frozenset({"succeeded", "partial", "failed", "cancelled"})


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
    current_node: Any | None = None
    completed_stages: dict[str, set[str]] = field(default_factory=dict)
    stage_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    resolved_sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    request_controller: Any | None = None


def _save_graph_cursor(ctx: _GraphWorkerContext) -> None:
    payload = {
        "schema_version": 3,
        "resolved_canonical_keys": sorted(ctx.budget.resolved_canonical_keys),
        "queue": [
            {
                "seed_telegram_id": q.seed_telegram_id,
                "seed_source_id": q.seed_source_id,
                "depth": q.depth,
                "username": q.username,
                "access_hash": q.access_hash,
            }
            for q in ctx.queue
        ],
        "current_node": (
            {
                "seed_telegram_id": ctx.current_node.seed_telegram_id,
                "seed_source_id": ctx.current_node.seed_source_id,
                "depth": ctx.current_node.depth,
                "username": ctx.current_node.username,
                "access_hash": ctx.current_node.access_hash,
            }
            if ctx.current_node is not None
            else None
        ),
        "completed_stages": {
            key: sorted(value) for key, value in ctx.completed_stages.items()
        },
        "stage_results": ctx.stage_results,
        "resolved_sources": ctx.resolved_sources,
        "parent_map": {
            str(key): value for key, value in ctx.parent_by_telegram_id.items()
        },
        "request_control": (
            ctx.request_controller.snapshot()
            if ctx.request_controller is not None
            else {"reserved_total": 0}
        ),
        "termination": {
            "reason": ctx.run.run_termination_reason,
            "error_code": ctx.run.last_error_code,
        },
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
    now = _utcnow()
    ctx.job.state = "failed"
    ctx.job.available_at = None
    ctx.job.lease_until = None
    ctx.job.lease_owner = None
    ctx.job.last_error_code = "flood_wait"
    ctx.job.updated_at = now
    ctx.run.state = "failed"
    ctx.run.phase = "done"
    ctx.run.last_error_code = "flood_wait"
    ctx.run.run_termination_reason = "flood_wait"
    ctx.run.pool_exhausted = False
    ctx.run.pool_exhausted_reason = None
    ctx.run.finished_at = now
    _save_graph_cursor(ctx)
    await ctx.session.flush()
    return {"outcome": "failed", "error": "flood_wait", "run_id": ctx.run.id}


async def _finish_graph_request_cap(ctx: _GraphWorkerContext) -> dict[str, Any]:
    now = _utcnow()
    ctx.run.state = "partial"
    ctx.run.phase = "done"
    ctx.run.run_termination_reason = "request_cap"
    ctx.run.pool_exhausted = False
    ctx.run.pool_exhausted_reason = None
    ctx.run.last_error_code = None
    ctx.run.finished_at = now
    ctx.job.state = "succeeded"
    ctx.job.available_at = None
    ctx.job.lease_until = None
    ctx.job.lease_owner = None
    ctx.job.last_error_code = None
    ctx.job.updated_at = now
    _save_graph_cursor(ctx)
    await ctx.session.flush()
    return {"outcome": "partial", "reason": "request_cap", "run_id": ctx.run.id}


async def _finish_graph_control_failure(
    ctx: _GraphWorkerContext, error: str
) -> dict[str, Any]:
    now = _utcnow()
    ctx.run.state = "failed"
    ctx.run.phase = "done"
    ctx.run.run_termination_reason = "request_control_violation"
    ctx.run.last_error_code = error
    ctx.run.pool_exhausted = False
    ctx.run.pool_exhausted_reason = None
    ctx.run.finished_at = now
    ctx.job.state = "failed"
    ctx.job.available_at = None
    ctx.job.lease_until = None
    ctx.job.lease_owner = None
    ctx.job.last_error_code = error
    ctx.job.updated_at = now
    _save_graph_cursor(ctx)
    await ctx.session.flush()
    return {"outcome": "failed", "error": error, "run_id": ctx.run.id}


async def _finish_graph_success(ctx: _GraphWorkerContext) -> dict[str, Any]:
    now = _utcnow()
    ctx.run.state = "succeeded"
    ctx.run.finished_at = now
    ctx.run.phase = "done"
    ctx.run.run_termination_reason = "completed"
    ctx.run.counters_json = _dumps_counters(ctx.budget.to_counters())
    ctx.current_node = None
    _save_graph_cursor(ctx)
    ctx.job.state = "succeeded"
    ctx.job.lease_until = None
    ctx.job.lease_owner = None
    ctx.job.available_at = None
    ctx.job.updated_at = now
    await ctx.session.flush()
    return {
        "outcome": "succeeded",
        "run_id": ctx.run.id,
        "counters": ctx.budget.to_counters(),
    }


async def _finish_graph_cancelled(ctx: _GraphWorkerContext) -> dict[str, Any]:
    now = _utcnow()
    ctx.run.state = "cancelled"
    ctx.run.finished_at = now
    ctx.run.last_error_code = "cancel_requested"
    ctx.run.run_termination_reason = "cancelled"
    ctx.job.state = "cancelled"
    ctx.job.lease_until = None
    ctx.job.lease_owner = None
    ctx.job.available_at = None
    ctx.job.updated_at = now
    _save_graph_cursor(ctx)
    await ctx.session.flush()
    return {"outcome": "cancelled", "run_id": ctx.run.id}
