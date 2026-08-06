from __future__ import annotations

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *

from telegram_lead_discovery.source_discovery.worker_parts.core import (
    _dumps_counters,
    _loads_counters,
    _utcnow,
)
from telegram_lead_discovery.source_discovery.worker_parts.lifecycle import _fail_run
from telegram_lead_discovery.source_discovery.worker_parts.registry import _load_dismissed_sources
from telegram_lead_discovery.source_discovery.worker_parts.graph_state import (
    TERMINAL_GRAPH_LIKE,
    _GraphWorkerContext,
    _finish_graph_cancelled,
    _finish_graph_success,
    _graph_maybe_heartbeat,
    _park_graph_flood,
    _save_graph_cursor,
)


async def process_graph_discovery_job(
    session: AsyncSession,
    job: Job,
    gateway: TelegramGateway,
    *,
    cancel_requested: bool = False,
) -> dict[str, Any]:
    """Execute one claimed ``discovery`` (graph) job with public-only BFS."""
    from telegram_lead_discovery.collector.ports import GraphEdgeDTO, PublicSourceRef
    from telegram_lead_discovery.source_discovery.graph_discovery import (
        JOB_TYPE_GRAPH_DISCOVERY,
        MAX_GRAPH_DEPTH,
        MAX_OUTGOING_EDGES_PER_SEED,
        MAX_RESOLVE_OPS,
        MAX_UNIQUE_GRAPH_CANDIDATES,
        GraphBudget,
        GraphCandidateResult,
        GraphQueueItem,
        collect_edges_for_seed,
        load_graph_seeds,
        load_registry_index,
        persist_graph_candidate,
        plan_edge_outcome,
    )

    if job.job_type != JOB_TYPE_GRAPH_DISCOVERY:
        raise ValueError(f"unexpected_job_type:{job.job_type}")

    payload = json.loads(job.payload_json or "{}")
    run_id = int(payload["run_id"])
    run = await session.get(DiscoveryRun, run_id)
    if run is None or run.run_type != "graph":
        job.state = "failed"
        job.last_error_code = "run_not_found"
        job.updated_at = _utcnow()
        await session.flush()
        return {"outcome": "failed", "error": "run_not_found"}

    if run.state in TERMINAL_GRAPH_LIKE:
        job.state = (
            "cancelled"
            if run.state == "cancelled"
            else ("failed" if run.state == "failed" else "succeeded")
        )
        job.updated_at = _utcnow()
        await session.flush()
        return {"outcome": "already_terminal", "run_state": run.state}

    now = _utcnow()
    if run.state == "queued":
        run.state = "running"
        run.started_at = run.started_at or now
    run.phase = run.phase or "expand"
    await session.flush()

    registry = await load_registry_index(session)
    dismissed = await _load_dismissed_sources(session)
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
    )
    # Restore resolved keys / queue from prior FloodWait degraded progress.
    raw_keys = json.loads(run.cursor_json or "{}")
    if isinstance(raw_keys, dict):
        for item in raw_keys.get("resolved_canonical_keys", []) or []:
            budget.resolved_canonical_keys.add(str(item))
        queue_payload = raw_keys.get("queue") or []
    else:
        queue_payload = []

    seeds = await load_graph_seeds(session, run)
    parent_map = {s.seed_telegram_id: s.seed_source_id or 0 for s in seeds}
    if queue_payload:
        queue = [
            GraphQueueItem(
                seed_telegram_id=int(q["seed_telegram_id"]),
                seed_source_id=q.get("seed_source_id"),
                depth=int(q["depth"]),
                username=q.get("username"),
            )
            for q in queue_payload
        ]
    else:
        queue = list(seeds)
        for seed in seeds:
            budget.resolved_canonical_keys.add(f"peer:{seed.seed_telegram_id}")

    ctx = _GraphWorkerContext(
        session=session,
        gateway=gateway,
        job=job,
        run=run,
        budget=budget,
        registry=registry,
        dismissed=dismissed,
        cancel_requested=cancel_requested,
        last_heartbeat_at=now,
        queue=queue,
        parent_by_telegram_id={k: v for k, v in parent_map.items() if v},
    )

    while ctx.queue:
        if ctx.cancel_requested or run.state == "cancelled":
            return await _finish_graph_cancelled(ctx)
        await _graph_maybe_heartbeat(ctx)
        node = ctx.queue.pop(0)
        if node.depth >= budget.max_depth:
            # Leaf: do not expand further (depth-2 findings are terminals).
            continue
        await session.commit()
        try:
            edges = await collect_edges_for_seed(
                gateway,
                seed=node,
                outgoing_cap=budget.max_outgoing_edges,
            )
        except GatewayFloodWait as exc:
            _save_graph_cursor(ctx)
            return await _park_graph_flood(ctx, exc.until)
        except GatewayUnauthorized:
            return await _fail_run(session, job, run, "unauthorized")
        except GatewayFrozen:
            return await _fail_run(session, job, run, "frozen")
        except GatewaySourceInaccessible:
            continue
        except GatewayTransientError:
            _save_graph_cursor(ctx)
            job.state = "retry_wait"
            job.available_at = _utcnow() + timedelta(seconds=30)
            job.last_error_code = "transient_error"
            job.updated_at = _utcnow()
            run.counters_json = _dumps_counters(budget.to_counters())
            await session.flush()
            return {"outcome": "retry_wait", "error": "transient_error"}

        child_depth = node.depth + 1
        for edge in edges:
            if ctx.cancel_requested:
                return await _finish_graph_cancelled(ctx)
            planned = plan_edge_outcome(
                edge,
                child_depth=child_depth,
                budget=budget,
                registry=ctx.registry,
                dismissed=ctx.dismissed,
            )
            snap = planned.snapshot
            if planned.outcome == "candidate" and snap is None:
                if budget.remaining_resolves() <= 0:
                    budget.budget_skipped_total += 1
                    planned = GraphCandidateResult(
                        outcome="budget_skipped",
                        method=planned.method,
                        depth=planned.depth,
                        raw_reference=planned.raw_reference,
                        normalized_reference=planned.normalized_reference,
                        parent_source_id=planned.parent_source_id,
                        seed_telegram_id=planned.seed_telegram_id,
                        snapshot=planned.snapshot,
                        source_id=planned.source_id,
                        evidence_message_id=planned.evidence_message_id,
                    )
                else:
                    await session.commit()
                    try:
                        snap = await gateway.resolve_public_source(
                            PublicSourceRef(
                                schema_version=1,
                                username_or_url=planned.normalized_reference or edge.raw_reference,
                            )
                        )
                        budget.resolves_used += 1
                    except GatewayFloodWait as exc:
                        ctx.queue.insert(0, node)
                        _save_graph_cursor(ctx)
                        return await _park_graph_flood(ctx, exc.until)
                    except GatewaySourceInaccessible:
                        budget.unsupported_total += 1
                        await persist_graph_candidate(
                            session,
                            run=run,
                            result=GraphCandidateResult(
                                outcome="unsupported_source",
                                method=planned.method,
                                depth=planned.depth,
                                raw_reference=planned.raw_reference,
                                normalized_reference=planned.normalized_reference,
                                parent_source_id=planned.parent_source_id,
                                seed_telegram_id=planned.seed_telegram_id,
                                evidence_message_id=planned.evidence_message_id,
                            ),
                            parent_source_id=node.seed_source_id,
                            budget=budget,
                        )
                        continue
                    resolved_edge = GraphEdgeDTO(
                        schema_version=1,
                        edge_type=edge.edge_type,
                        seed_telegram_id=edge.seed_telegram_id,
                        raw_reference=edge.raw_reference,
                        normalized_username=snap.username.lower(),
                        target=snap,
                        evidence_message_id=edge.evidence_message_id,
                    )
                    budget.resolved_canonical_keys.discard(
                        f"username:{planned.normalized_reference}"
                    )
                    planned = plan_edge_outcome(
                        resolved_edge,
                        child_depth=child_depth,
                        budget=budget,
                        registry=ctx.registry,
                        dismissed=ctx.dismissed,
                    )
                    snap = planned.snapshot

            if planned.outcome in {
                "depth_skipped",
                "budget_skipped",
                "duplicate_in_run",
                "dismissed_suppressed",
                "unsupported_source",
                "invalid_reference",
                "registry_suppressed",
            }:
                await persist_graph_candidate(
                    session,
                    run=run,
                    result=planned,
                    parent_source_id=node.seed_source_id,
                    budget=budget,
                    snapshot=snap,
                )
                continue

            source = await persist_graph_candidate(
                session,
                run=run,
                result=planned,
                parent_source_id=node.seed_source_id,
                budget=budget,
                snapshot=snap,
            )
            if (
                source is not None
                and snap is not None
                and child_depth < budget.max_depth
                and planned.outcome in {"candidate", "merged"}
            ):
                already_queued = any(q.seed_telegram_id == snap.telegram_id for q in ctx.queue)
                if not already_queued:
                    ctx.queue.append(
                        GraphQueueItem(
                            seed_telegram_id=snap.telegram_id,
                            seed_source_id=source.id,
                            depth=child_depth,
                            username=snap.username.lower(),
                        )
                    )
                    ctx.parent_by_telegram_id[snap.telegram_id] = source.id

        _save_graph_cursor(ctx)
        run.counters_json = _dumps_counters(budget.to_counters())
        await session.flush()

    return await _finish_graph_success(ctx)
