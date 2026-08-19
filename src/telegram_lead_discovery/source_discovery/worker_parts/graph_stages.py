"""Durable stages and candidate persistence for graph discovery."""

from __future__ import annotations

from typing import Any

from telegram_lead_discovery.collector.ports import (
    GraphEdgeDTO,
    GraphSampleRequest,
    SourceRef,
)
from telegram_lead_discovery.source_discovery.graph_candidate_resolution import (
    resolve_planned_candidate,
)
from telegram_lead_discovery.source_discovery.graph_cursor import (
    edge_from_dict,
    edge_to_dict,
    node_key,
    snapshot_to_dict,
)
from telegram_lead_discovery.source_discovery.graph_discovery import (
    GraphCandidateResult,
    GraphQueueItem,
    filter_allowed_public_edges,
    persist_graph_candidate,
    plan_edge_outcome,
)
from telegram_lead_discovery.source_discovery.graph_post_persistence import (
    persist_graph_posts,
)
from telegram_lead_discovery.source_discovery.worker_parts.graph_state import (
    _save_graph_cursor,
)
from telegram_lead_discovery.storage.models import TelegramSource

GRAPH_NODE_STAGES = (
    "recommendations",
    "linked_discussion",
    "message_sample_100",
)


def _source_ref(node: GraphQueueItem) -> SourceRef:
    return SourceRef(
        schema_version=1,
        source_id=node.seed_source_id or 0,
        telegram_id=node.seed_telegram_id or None,
        username=node.username,
        access_hash=node.access_hash,
    )


async def resolve_node(ctx: Any, node: GraphQueueItem) -> GraphQueueItem:
    key = node_key(node)
    if "resolve" in ctx.completed_stages.get(key, set()):
        return node
    resolver = getattr(ctx.gateway, "resolve_graph_source", None)
    if resolver is None:
        ctx.completed_stages.setdefault(key, set()).add("resolve")
        _save_graph_cursor(ctx)
        await ctx.session.commit()
        return node
    snapshot = await resolver(_source_ref(node))
    resolved = GraphQueueItem(
        seed_telegram_id=snapshot.telegram_id,
        seed_source_id=node.seed_source_id,
        depth=node.depth,
        username=snapshot.username or node.username,
        access_hash=snapshot.access_hash,
    )
    if resolved.seed_source_id:
        source = await ctx.session.get(TelegramSource, resolved.seed_source_id)
        if source is not None:
            source.telegram_id = resolved.seed_telegram_id
            source.access_hash = resolved.access_hash
            if resolved.username:
                source.username_normalized = resolved.username.casefold()
    ctx.current_node = resolved
    ctx.resolved_sources[key] = snapshot_to_dict(snapshot)
    ctx.completed_stages.setdefault(node_key(resolved), set()).add("resolve")
    _save_graph_cursor(ctx)
    await ctx.session.commit()
    return resolved


async def load_or_fetch_stage(
    ctx: Any,
    node: GraphQueueItem,
    stage: str,
) -> tuple[list[GraphEdgeDTO], bool]:
    key = node_key(node)
    completed = ctx.completed_stages.setdefault(key, set())
    if stage in completed:
        saved = ctx.stage_results.setdefault(key, {}).get(stage)
        return _saved_edges(saved), True
    saved = ctx.stage_results.setdefault(key, {}).get(stage)
    if saved is not None:
        return _saved_edges(saved), False

    source = _source_ref(node)
    edges: list[GraphEdgeDTO] = []
    if stage == "recommendations":
        snapshots = await ctx.gateway.get_recommendations(
            source, ctx.budget.max_outgoing_edges
        )
        edges = [
            GraphEdgeDTO(
                schema_version=1,
                edge_type="recommendation",
                seed_telegram_id=node.seed_telegram_id,
                raw_reference=f"@{snapshot.username}",
                normalized_username=snapshot.username.casefold(),
                target=snapshot,
            )
            for snapshot in snapshots
        ]
    elif stage == "linked_discussion":
        snapshot = await ctx.gateway.get_linked_discussion(source)
        if snapshot is not None and snapshot.username:
            edges = [
                GraphEdgeDTO(
                    schema_version=1,
                    edge_type="linked_discussion",
                    seed_telegram_id=node.seed_telegram_id,
                    raw_reference=f"@{snapshot.username}",
                    normalized_username=snapshot.username.casefold(),
                    target=snapshot,
                )
            ]
    elif stage == "message_sample_100":
        sampler = getattr(ctx.gateway, "sample_public_graph", None)
        if sampler is None:
            edges = list(
                await ctx.gateway.sample_public_graph_edges(
                    GraphSampleRequest(
                        schema_version=1,
                        source=source,
                        message_limit=100,
                    )
                )
            )
            messages = ()
        else:
            sample = await sampler(
                GraphSampleRequest(
                    schema_version=1,
                    source=source,
                    message_limit=100,
                )
            )
            edges = list(sample.edges)
            messages = sample.messages
        request_ordinal = int(getattr(ctx.request_controller, "reserved_total", 0))
        posts_persisted = await persist_graph_posts(
            ctx.session,
            run_id=ctx.run.id,
            source_id=node.seed_source_id,
            source_telegram_id=node.seed_telegram_id,
            source_username=node.username,
            request_ordinal=request_ordinal,
            messages=messages,
        )
        ctx.stage_results[key][stage] = {
            "schema_version": 1,
            "edges": [edge_to_dict(edge) for edge in edges],
            "source_id": node.seed_source_id,
            "source_telegram_id": node.seed_telegram_id,
            "source_username": node.username,
            "request_ordinal": request_ordinal,
            "posts_persisted": posts_persisted,
        }
    else:
        raise ValueError(f"unknown_graph_stage:{stage}")

    if stage != "message_sample_100":
        ctx.stage_results[key][stage] = [edge_to_dict(edge) for edge in edges]
    _save_graph_cursor(ctx)
    await ctx.session.commit()
    return edges, False


def _saved_edges(saved: Any) -> list[GraphEdgeDTO]:
    if isinstance(saved, dict):
        values = saved.get("edges") or []
    else:
        values = saved or []
    return [edge_from_dict(item) for item in values if isinstance(item, dict)]


async def process_stage_edges(
    ctx: Any,
    node: GraphQueueItem,
    stage: str,
    edges: list[GraphEdgeDTO],
    *,
    remaining_edges: int,
) -> int:
    public = list(filter_allowed_public_edges(edges))[: max(0, remaining_edges)]
    prepared: list[tuple[GraphCandidateResult, Any | None]] = []
    for edge in public:
        planned = plan_edge_outcome(
            edge,
            child_depth=node.depth + 1,
            budget=ctx.budget,
            registry=ctx.registry,
            dismissed=ctx.dismissed,
        )
        snapshot = planned.snapshot
        if planned.outcome == "candidate" and snapshot is None:
            snapshot, planned = await resolve_planned_candidate(
                ctx, node, edge, planned
            )
        prepared.append((planned, snapshot))

    for planned, snapshot in prepared:
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
                ctx.session,
                run=ctx.run,
                result=planned,
                parent_source_id=node.seed_source_id,
                budget=ctx.budget,
                snapshot=snapshot,
            )
            continue

        source = await persist_graph_candidate(
            ctx.session,
            run=ctx.run,
            result=planned,
            parent_source_id=node.seed_source_id,
            budget=ctx.budget,
            snapshot=snapshot,
        )
        if (
            source is not None
            and snapshot is not None
            and node.depth + 1 < ctx.budget.max_depth
            and planned.outcome in {"candidate", "merged"}
        ):
            _enqueue_child(ctx, source.id, snapshot, node.depth + 1)

    key = node_key(node)
    ctx.completed_stages.setdefault(key, set()).add(stage)
    _save_graph_cursor(ctx)
    await ctx.session.commit()
    return remaining_edges - len(public)


def _enqueue_child(ctx: Any, source_id: int, snapshot: Any, depth: int) -> None:
    if any(item.seed_telegram_id == snapshot.telegram_id for item in ctx.queue):
        return
    if ctx.current_node is not None and ctx.current_node.seed_telegram_id == snapshot.telegram_id:
        return
    ctx.queue.append(
        GraphQueueItem(
            seed_telegram_id=snapshot.telegram_id,
            seed_source_id=source_id,
            depth=depth,
            username=snapshot.username.casefold(),
            access_hash=snapshot.access_hash,
        )
    )
    ctx.parent_by_telegram_id[snapshot.telegram_id] = source_id


__all__ = [
    "GRAPH_NODE_STAGES",
    "load_or_fetch_stage",
    "process_stage_edges",
    "resolve_node",
]
