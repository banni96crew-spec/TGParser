"""Persisted graph-discovery worker with graph-only request control."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.collector.ports import (
    GatewayFloodWait,
    GatewayFrozen,
    GatewayPermanentError,
    GatewaySourceInaccessible,
    GatewayTimeout,
    GatewayTransientError,
    GatewayUnauthorized,
    GraphCallCancelled,
    NestedTelegramRequest,
    RequestBudgetExhausted,
    TelegramGateway,
    UnsupportedBatchRequest,
    current_request_controller,
)
from telegram_lead_discovery.source_discovery.graph_cancel import (
    register_graph_cancel_event,
    unregister_graph_cancel_event,
)
from telegram_lead_discovery.source_discovery.graph_cursor import node_from_dict, node_key
from telegram_lead_discovery.source_discovery.graph_request_control import (
    GraphRequestController,
)
from telegram_lead_discovery.source_discovery.worker_parts.core import (
    _dumps_counters,
    _loads_counters,
    _utcnow,
)
from telegram_lead_discovery.source_discovery.worker_parts.graph_stages import (
    GRAPH_NODE_STAGES,
    load_or_fetch_stage,
    process_stage_edges,
    resolve_node,
)
from telegram_lead_discovery.source_discovery.worker_parts.graph_state import (
    TERMINAL_GRAPH_LIKE,
    _cursor_payload,
    _finish_graph_cancelled,
    _finish_graph_control_failure,
    _finish_graph_request_cap,
    _finish_graph_success,
    _graph_heartbeat_now,
    _graph_maybe_heartbeat,
    _GraphWorkerContext,
    _job_state_for_terminal,
    _parent_map,
    _park_graph_flood,
    _reservation_writer,
    _restore_queue,
    _save_graph_cursor,
    _transient_counts,
)
from telegram_lead_discovery.source_discovery.worker_parts.graph_timeout import (
    skip_remaining_graph_stages,
)
from telegram_lead_discovery.source_discovery.worker_parts.lifecycle import _fail_run
from telegram_lead_discovery.source_discovery.worker_parts.registry import (
    _load_dismissed_sources,
)
from telegram_lead_discovery.storage.jobs import (
    drop_inflight_discovery_job,
    mark_inflight_discovery_job,
)
from telegram_lead_discovery.storage.models import DiscoveryRun, Job


async def process_graph_discovery_job(
    session: AsyncSession,
    job: Job,
    gateway: TelegramGateway,
    *,
    cancel_requested: bool = False,
) -> dict[str, Any]:
    """Execute one claimed graph job; never changes ordinary search limits."""
    from telegram_lead_discovery.source_discovery.graph_discovery import (
        JOB_TYPE_GRAPH_DISCOVERY,
        MAX_GRAPH_DEPTH,
        MAX_OUTGOING_EDGES_PER_SEED,
        MAX_RESOLVE_OPS,
        MAX_UNIQUE_GRAPH_CANDIDATES,
        GraphBudget,
        load_graph_seeds,
        load_registry_index,
    )

    if job.job_type != JOB_TYPE_GRAPH_DISCOVERY:
        raise ValueError(f"unexpected_job_type:{job.job_type}")
    payload = json.loads(job.payload_json or "{}")
    run = await session.get(DiscoveryRun, int(payload["run_id"]))
    if run is None or run.run_type != "graph":
        job.state = "failed"
        job.last_error_code = "run_not_found"
        job.updated_at = _utcnow()
        await session.flush()
        return {"outcome": "failed", "error": "run_not_found"}
    if run.state in TERMINAL_GRAPH_LIKE:
        job.state = _job_state_for_terminal(run.state)
        job.updated_at = _utcnow()
        await session.flush()
        return {"outcome": "already_terminal", "run_state": run.state}

    cancel_event = register_graph_cancel_event(run.id)
    run_id = run.id
    job_id = job.id
    try:
        await session.refresh(run)
        await session.refresh(job)
        now = _utcnow()
        if run.state == "queued":
            run.state = "running"
            run.started_at = run.started_at or now
        run.phase = "expand"
        await session.flush()
        await session.commit()
        await session.refresh(run)
        await session.refresh(job)
        cursor = _cursor_payload(run.cursor_json)
        counters = _loads_counters(run.counters_json)
        budget = GraphBudget(
            max_depth=int(run.max_depth or MAX_GRAPH_DEPTH),
            max_outgoing_edges=int(run.expansion_cap or MAX_OUTGOING_EDGES_PER_SEED),
            candidate_cap=int(run.candidate_cap or MAX_UNIQUE_GRAPH_CANDIDATES),
            resolve_cap=MAX_RESOLVE_OPS,
            resolves_used=int(counters.get("resolves", 0)),
            candidates_created=int(counters.get("created_candidates", 0)),
            merged_total=int(counters.get("merged_candidates", 0)),
            depth_skipped_total=int(counters.get("depth_skipped_total", 0)),
            budget_skipped_total=int(counters.get("budget_skipped_total", 0)),
            unsupported_total=int(counters.get("unsupported_sources", 0)),
            invalid_total=int(counters.get("invalid_references", 0)),
            duplicate_in_run_total=int(counters.get("duplicate_in_run", 0)),
            dismissed_suppressed_total=int(counters.get("dismissed_suppressed", 0)),
            node_timeout_total=int(counters.get("node_timeout_total", 0)),
        )
        budget.resolved_canonical_keys.update(
            str(item) for item in cursor.get("resolved_canonical_keys", [])
        )
        seeds = await load_graph_seeds(session, run)
        if not cursor:
            budget.resolved_canonical_keys.update(
                f"peer:{seed.seed_telegram_id}" for seed in seeds
            )
        completed = {
            str(key): {str(stage) for stage in value}
            for key, value in (cursor.get("completed_stages") or {}).items()
            if isinstance(value, list)
        }
        request_state = cursor.get("request_control") or {}
        controller = GraphRequestController(
            reserved_total=int(request_state.get("reserved_total") or 0),
            persist_reservation=_reservation_writer(run.id, run),
            cancel_event=cancel_event,
        )
        ctx = _GraphWorkerContext(
            session=session,
            gateway=gateway,
            job=job,
            run=run,
            budget=budget,
            registry=await load_registry_index(session),
            dismissed=await _load_dismissed_sources(session),
            cancel_requested=cancel_requested,
            last_heartbeat_at=now,
            queue=_restore_queue(cursor, seeds),
            parent_by_telegram_id=_parent_map(cursor, seeds),
            current_node=(
                node_from_dict(cursor["current_node"])
                if isinstance(cursor.get("current_node"), dict)
                else None
            ),
            completed_stages=completed,
            stage_results=dict(cursor.get("stage_results") or {}),
            resolved_sources=dict(cursor.get("resolved_sources") or {}),
            request_controller=controller,
            transient_counts=_transient_counts(cursor),
        )

        async def _pulse() -> None:
            await _graph_heartbeat_now(ctx)

        controller._heartbeat = _pulse
        if _cancel_pending(ctx, cancel_event):
            return await _finish_graph_cancelled(ctx)
        mark_inflight_discovery_job(job_id)
        token = current_request_controller.set(controller)
        try:
            return await _execute_graph(ctx, cancel_event)
        finally:
            current_request_controller.reset(token)
            drop_inflight_discovery_job(job_id)
    finally:
        unregister_graph_cancel_event(run_id)


def _cancel_pending(ctx: _GraphWorkerContext, cancel_event: Any) -> bool:
    return bool(
        ctx.cancel_requested
        or ctx.run.state in {"cancelled", "cancelling"}
        or ctx.job.cancel_requested_at is not None
        or cancel_event.is_set()
    )


async def _execute_graph(ctx: _GraphWorkerContext, cancel_event: Any) -> dict[str, Any]:
    while ctx.current_node is not None or ctx.queue:
        if _cancel_pending(ctx, cancel_event):
            return await _finish_graph_cancelled(ctx)
        await _graph_maybe_heartbeat(ctx)
        if ctx.current_node is None:
            ctx.current_node = ctx.queue.pop(0)
            _save_graph_cursor(ctx)
            await ctx.session.commit()
        node = ctx.current_node
        if node.depth >= ctx.budget.max_depth:
            ctx.current_node = None
            _save_graph_cursor(ctx)
            await ctx.session.commit()
            continue
        try:
            node = await resolve_node(ctx, node)
            remaining = ctx.budget.max_outgoing_edges
            for stage in GRAPH_NODE_STAGES:
                edges, completed = await load_or_fetch_stage(ctx, node, stage)
                if completed:
                    remaining = max(0, remaining - len(edges))
                    continue
                remaining = await process_stage_edges(
                    ctx,
                    node,
                    stage,
                    edges,
                    remaining_edges=remaining,
                )
        except GraphCallCancelled:
            return await _finish_graph_cancelled(ctx)
        except GatewayTimeout:
            await skip_remaining_graph_stages(ctx)
            continue
        except GatewayFloodWait as exc:
            return await _park_graph_flood(ctx, exc.until)
        except RequestBudgetExhausted:
            return await _finish_graph_request_cap(ctx)
        except (UnsupportedBatchRequest, NestedTelegramRequest) as exc:
            return await _finish_graph_control_failure(ctx, str(exc))
        except GatewayUnauthorized:
            return await _fail_run(ctx.session, ctx.job, ctx.run, "unauthorized")
        except GatewayFrozen:
            return await _fail_run(ctx.session, ctx.job, ctx.run, "frozen")
        except GatewaySourceInaccessible as exc:
            ctx.run.last_error_code = str(exc) or "source_inaccessible"
            await skip_remaining_graph_stages(ctx, count_timeout=False)
            continue
        except GatewayPermanentError as exc:
            ctx.run.last_error_code = str(exc) or "permanent_error"
            await skip_remaining_graph_stages(ctx, count_timeout=False)
            continue
        except GatewayTransientError:
            if await _park_or_skip_transient(ctx, node):
                continue
            return {
                "outcome": "retry_wait",
                "error": "transient_error",
            }

        ctx.current_node = None
        ctx.run.counters_json = _dumps_counters(ctx.budget.to_counters())
        _save_graph_cursor(ctx)
        await ctx.session.commit()
    return await _finish_graph_success(ctx)


async def _park_or_skip_transient(ctx: _GraphWorkerContext, node: Any) -> bool:
    key = node_key(node)
    if ctx.transient_counts.get(key, 0) >= 1:
        await skip_remaining_graph_stages(ctx)
        return True
    ctx.transient_counts[key] = ctx.transient_counts.get(key, 0) + 1
    _save_graph_cursor(ctx)
    ctx.job.state = "retry_wait"
    ctx.job.available_at = _utcnow() + timedelta(seconds=30)
    ctx.job.last_error_code = "transient_error"
    ctx.job.updated_at = _utcnow()
    await ctx.session.flush()
    return False
